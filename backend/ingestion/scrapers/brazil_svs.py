"""
Brazil SVS (Secretaria de Vigilância em Saúde) scraper.

Data source: OpenDataSUS SIVEP-Gripe (SARI surveillance system)
https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026

Downloads weekly-updated CSV files from S3, filters flu-confirmed SRAG cases,
and aggregates by state + epidemiological week + flu type.

CSV files are 100-320MB each, semicolon-delimited, streamed to avoid
loading fully into memory.
"""

import csv
import io
import re
from collections import defaultdict
from datetime import datetime

import structlog

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

BRAZIL_STATES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}

DATASET_PAGE_URL = "https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026"

# Frozen (closed) CSV banks — filenames are stable
FROZEN_CSVS = {
    2019: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2019/INFLUD19-26-06-2025.csv",
    2020: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2020/INFLUD20-26-06-2025.csv",
    2021: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2021/INFLUD21-26-06-2025.csv",
    2022: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2022/INFLUD22-26-06-2025.csv",
    2023: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2023/INFLUD23-26-06-2025.csv",
    2024: "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2024/INFLUD24-26-06-2025.csv",
}


def _classify_flu_type(tp_flu_pcr: str, pcr_fluasu: str) -> str | None:
    """Map PCR result codes to flu type string.

    Returns None if the row is not a flu case.
    """
    if tp_flu_pcr == "1":  # Influenza A
        if pcr_fluasu == "1":
            return "H1N1pdm09"
        elif pcr_fluasu == "2":
            return "H3N2"
        else:
            return "A (unsubtyped)"
    elif tp_flu_pcr == "2":  # Influenza B
        return "B"
    return None


def _epiweek_to_date(year: int, week: int) -> datetime:
    """Convert epidemiological year+week to a Monday date (ISO week)."""
    return datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u")


class BrazilSVSScraper(BaseScraper):
    """Scraper for Brazil SIVEP-Gripe flu data via OpenDataSUS."""

    country_code = "BR"
    source_name = "brazil_svs"

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch the most recent SRAG CSV, filter flu cases, aggregate by state+week."""
        csv_url = await self._find_csv_url_for_year()
        if not csv_url:
            logger.error("Could not find live CSV URL on dataset page")
            return []
        logger.info("Downloading live CSV", url=csv_url)
        return await self._fetch_and_aggregate(csv_url)

    async def fetch_year(self, year: int) -> list[FluCaseRecord]:
        """Fetch and aggregate a specific year's CSV (for backfill)."""
        if year in FROZEN_CSVS:
            url = FROZEN_CSVS[year]
        else:
            url = await self._find_csv_url_for_year(year)
            if not url:
                raise RuntimeError(f"Cannot find CSV URL for year {year}")
        logger.info("Downloading CSV", year=year, url=url)
        return await self._fetch_and_aggregate(url, filter_year=year)

    async def _find_csv_url_for_year(self, year: int | None = None) -> str | None:
        """Scrape dataset page for a CSV URL.

        If year is given, look for that year's CSV. If None, return the
        most recent (highest-year) CSV found on the page.
        """
        try:
            resp = await self._get(DATASET_PAGE_URL)
            html = resp.text

            # Find all S3 SRAG CSV links on the page
            all_links = re.findall(
                r'(https://s3[^"\'<>\s]+/SRAG/(\d{4})/INFLUD[^"\'<>\s]+\.csv)',
                html, re.IGNORECASE,
            )
            if not all_links:
                logger.warning("No CSV links found on dataset page")
                return None

            if year is not None:
                # Find link matching the requested year
                for url, link_year in all_links:
                    if int(link_year) == year:
                        return url
                logger.warning("No CSV URL found for year", year=year)
                return None
            else:
                # Return the highest-year link (most recent live bank)
                best = max(all_links, key=lambda x: int(x[1]))
                return best[0]

        except Exception as e:
            logger.error("Failed to scrape dataset page", error=str(e))
            return None

    async def _fetch_and_aggregate(
        self, csv_url: str, filter_year: int | None = None
    ) -> list[FluCaseRecord]:
        """Stream CSV, filter flu-positive rows, aggregate by state+week+type."""
        # counts[(state_name, week_date, flu_type)] = case_count
        counts: dict[tuple, int] = defaultdict(int)
        rows_read = 0
        flu_rows = 0

        async with self.client.stream("GET", csv_url, timeout=300.0) as resp:
            resp.raise_for_status()

            # Build an async line iterator and wrap for csv.reader
            buffer = ""
            header = None
            col_idx = {}

            async for chunk in resp.aiter_text(chunk_size=64 * 1024):
                buffer += chunk
                lines = buffer.split("\n")
                buffer = lines.pop()  # Keep incomplete last line

                for line in lines:
                    if header is None:
                        # Parse header row
                        header = next(csv.reader([line], delimiter=";"))
                        for i, col in enumerate(header):
                            col_idx[col.strip()] = i
                        # Verify required columns exist
                        required = ["SG_UF_NOT", "SEM_NOT", "DT_NOTIFIC",
                                    "CLASSI_FIN", "POS_PCRFLU", "TP_FLU_PCR",
                                    "PCR_FLUASU"]
                        missing = [c for c in required if c not in col_idx]
                        if missing:
                            logger.error("Missing CSV columns", missing=missing,
                                         available=list(col_idx.keys())[:20])
                            return []
                        continue

                    rows_read += 1
                    try:
                        row = next(csv.reader([line], delimiter=";"))
                    except StopIteration:
                        continue

                    if len(row) <= max(col_idx[c] for c in col_idx if c in
                                       ["SG_UF_NOT", "SEM_NOT", "DT_NOTIFIC",
                                        "CLASSI_FIN", "POS_PCRFLU"]):
                        continue

                    state_code = row[col_idx["SG_UF_NOT"]].strip()
                    sem_not = row[col_idx["SEM_NOT"]].strip()
                    dt_notific = row[col_idx["DT_NOTIFIC"]].strip()
                    classi_fin = row[col_idx["CLASSI_FIN"]].strip()
                    pos_pcrflu = row[col_idx["POS_PCRFLU"]].strip()
                    tp_flu_pcr = row[col_idx["TP_FLU_PCR"]].strip()
                    pcr_fluasu = row[col_idx["PCR_FLUASU"]].strip()

                    # Filter: flu-confirmed SRAG cases only
                    is_flu = classi_fin == "1" or pos_pcrflu == "1"
                    if not is_flu:
                        continue

                    # Determine year from notification date
                    try:
                        if "/" in dt_notific:
                            notif_date = datetime.strptime(dt_notific, "%d/%m/%Y")
                        elif "-" in dt_notific:
                            notif_date = datetime.strptime(dt_notific, "%Y-%m-%d")
                        else:
                            continue
                        notif_year = notif_date.year
                    except (ValueError, TypeError):
                        continue

                    if filter_year and notif_year != filter_year:
                        continue

                    # Determine epi week date
                    try:
                        week_num = int(sem_not)
                        week_date = _epiweek_to_date(notif_year, week_num)
                    except (ValueError, TypeError):
                        continue

                    # Map state code to name
                    state_name = BRAZIL_STATES.get(state_code)
                    if not state_name:
                        continue

                    # Classify flu type
                    flu_type = _classify_flu_type(tp_flu_pcr, pcr_fluasu)
                    if flu_type is None:
                        flu_type = "unknown"

                    counts[(state_name, week_date, flu_type)] += 1
                    flu_rows += 1

            # Process any remaining buffer
            if buffer.strip() and header is not None:
                try:
                    row = next(csv.reader([buffer], delimiter=";"))
                    # Same processing as above — but simpler to skip the last partial line
                except (StopIteration, csv.Error):
                    pass

        logger.info("CSV processing complete",
                    rows_read=rows_read, flu_rows=flu_rows,
                    aggregated_records=len(counts))

        # Convert aggregated counts to FluCaseRecords
        records = []
        for (state_name, week_date, flu_type), count in counts.items():
            records.append(FluCaseRecord(
                time=week_date,
                country_code="BR",
                region=state_name,
                new_cases=count,
                flu_type=flu_type,
                source=self.source_name,
            ))

        return records
