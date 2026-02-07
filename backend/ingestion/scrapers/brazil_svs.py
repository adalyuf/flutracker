"""
Brazil SVS (Secretaria de Vigilância em Saúde) scraper.

Data source: InfoGripe / SIVEP-Gripe (SARI surveillance system)
https://info.gripe.fiocruz.br/
Provides state-level SARI (Severe Acute Respiratory Infection) data
with flu subtype breakdown.
"""

from datetime import datetime, timedelta

import structlog

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

INFOGRIPE_API = "https://info.gripe.fiocruz.br/data/detailed/1/1"

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


class BrazilSVSScraper(BaseScraper):
    """Scraper for Brazil SIVEP-Gripe/InfoGripe flu data."""

    country_code = "BR"
    source_name = "brazil_svs"

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest Brazilian flu surveillance data."""
        records = []

        try:
            records = await self._fetch_infogripe()
        except Exception as e:
            logger.error("InfoGripe fetch failed", error=str(e))

        return records

    async def _fetch_infogripe(self) -> list[FluCaseRecord]:
        """Fetch from InfoGripe/Fiocruz API."""
        # InfoGripe provides weekly SARI data by state with virus identification
        current_year = datetime.utcnow().year

        records = []

        # Fetch data for each state
        for state_code, state_name in BRAZIL_STATES.items():
            try:
                url = f"https://info.gripe.fiocruz.br/data/detailed/1/1/{state_code}"
                params = {"year": current_year}
                response = await self._get(url, params=params)
                data = response.json()

                state_records = self._parse_state_data(state_name, data)
                records.extend(state_records)

            except Exception as e:
                logger.warning(
                    "InfoGripe state fetch failed",
                    state=state_code,
                    error=str(e),
                )
                continue

        return records

    def _parse_state_data(self, state_name: str, data: dict) -> list[FluCaseRecord]:
        """Parse InfoGripe state-level response."""
        records = []
        entries = data if isinstance(data, list) else data.get("data", [])

        for entry in entries:
            epi_week = entry.get("epiweek") or entry.get("SE")
            year = entry.get("epiyear") or entry.get("ano")

            if not (epi_week and year):
                continue

            try:
                week_date = datetime.strptime(f"{year}-W{int(epi_week):02d}-1", "%G-W%V-%u")
            except (ValueError, TypeError):
                continue

            # SARI cases with influenza identification
            flu_cases = entry.get("casos_influenza", 0) or 0
            sari_cases = entry.get("casos", entry.get("srag", 0)) or 0

            # Subtype breakdown where available
            subtypes = {
                "H1N1": entry.get("influenza_a_h1n1_pdm09", 0) or entry.get("flu_a_h1n1", 0),
                "H3N2": entry.get("influenza_a_h3n2", 0) or entry.get("flu_a_h3n2", 0),
                "A (unsubtyped)": entry.get("influenza_a_ns", 0) or entry.get("flu_a_ns", 0),
                "B (lineage unknown)": entry.get("influenza_b", 0) or entry.get("flu_b", 0),
            }

            has_subtypes = any(v and int(v) > 0 for v in subtypes.values())

            if has_subtypes:
                for flu_type, count in subtypes.items():
                    if count and int(count) > 0:
                        records.append(FluCaseRecord(
                            time=week_date,
                            country_code="BR",
                            region=state_name,
                            new_cases=int(count),
                            flu_type=flu_type,
                            source=self.source_name,
                        ))
            elif flu_cases and int(flu_cases) > 0:
                records.append(FluCaseRecord(
                    time=week_date,
                    country_code="BR",
                    region=state_name,
                    new_cases=int(flu_cases),
                    flu_type="unknown",
                    source=self.source_name,
                ))
            elif sari_cases and int(sari_cases) > 0:
                # Use SARI as proxy when flu-specific data unavailable
                records.append(FluCaseRecord(
                    time=week_date,
                    country_code="BR",
                    region=state_name,
                    new_cases=int(sari_cases),
                    flu_type="unknown",
                    source=self.source_name,
                ))

        return records
