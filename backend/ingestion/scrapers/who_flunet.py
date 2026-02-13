"""
WHO FluNet scraper — baseline data source for all countries.

FluNet provides weekly influenza surveillance data reported by WHO member states.
Data includes case counts by flu subtype (A/H1N1, A/H3N2, B, etc.) at country level.
Updated weekly, typically with 1-2 week reporting lag.

Data source: https://www.who.int/tools/flunet
API endpoint: https://xmart-api-public.who.int/FLUMART/VIW_FNT (WHO xMart OData)
"""

from datetime import datetime, timedelta, timezone

import structlog

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

# WHO xMart public OData API for FluNet
FLUNET_API = "https://xmart-api-public.who.int/FLUMART/VIW_FNT"

# Subtype fields in the API response and our standard names

# Preferred subtype fields in priority order (avoid double-counting).
# Use specific subtypes first; fall back to aggregate INF_A/INF_B only if
# no specific subtypes had counts.
SPECIFIC_SUBTYPES = {
    "AH1N12009": "H1N1",
    "AH3": "H3N2",
    "AH5": "H5N1",
    "AH7N9": "H7N9",
    "BYAM": "B/Yamagata",
    "BVIC": "B/Victoria",
}

AGGREGATE_SUBTYPES = {
    "INF_A": "A (unsubtyped)",
    "INF_B": "B (lineage unknown)",
}

# FluNet publishes UK constituent entities separately.
# Normalize them to GB so the dashboard treats them as one country.
UK_COMPONENT_TO_GB = {"XE", "XI", "XS", "XW"}


class WHOFluNetScraper(BaseScraper):
    """Scraper for WHO FluNet global influenza data."""

    source_name = "who_flunet"
    country_code = ""  # Handles all countries

    def __init__(self, country_codes: list[str] | None = None):
        super().__init__()
        self.target_countries = country_codes

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest FluNet data (last 4 weeks) for target countries."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(weeks=4)
        return await self.fetch_range(
            start_date.year, start_date.isocalendar()[1],
            end_date.year, end_date.isocalendar()[1],
        )

    async def fetch_range(
        self,
        start_year: int, start_week: int,
        end_year: int, end_week: int,
        top: int = 120000,
    ) -> list[FluCaseRecord]:
        """Fetch FluNet data for a year/week range via xMart OData API."""
        # Build OData filter
        start_yw = start_year * 100 + start_week
        end_yw = end_year * 100 + end_week
        odata_filter = f"ISOYW ge {start_yw} and ISOYW le {end_yw}"

        if self.target_countries:
            codes = ",".join(f"'{c}'" for c in self.target_countries)
            odata_filter += f" and ISO2 in ({codes})"

        params = {
            "$filter": odata_filter,
            "$top": top,
        }

        records = []
        url = FLUNET_API

        while url:
            logger.info("FluNet API request", url=url, filter=odata_filter)
            response = await self._get(url, params=params if url == FLUNET_API else None)
            data = response.json()

            entries = data.get("value", [])
            logger.info("FluNet batch received", count=len(entries))

            for entry in entries:
                parsed = self._parse_entry(entry)
                if parsed:
                    records.extend(parsed)

            # Follow OData pagination
            url = data.get("@odata.nextLink")
            params = None  # nextLink includes params already

        # Aggregate any duplicate logical keys within this fetch window.
        # This is especially important for UK normalization where multiple
        # constituent entries are merged into GB.
        aggregated: dict[tuple, FluCaseRecord] = {}
        for r in records:
            key = (r.time, r.country_code, r.region, r.city, r.flu_type, r.source)
            if key in aggregated:
                aggregated[key].new_cases += int(r.new_cases)
            else:
                aggregated[key] = FluCaseRecord(
                    time=r.time,
                    country_code=r.country_code,
                    region=r.region,
                    city=r.city,
                    new_cases=int(r.new_cases),
                    flu_type=r.flu_type,
                    source=r.source,
                )

        normalized = list(aggregated.values())
        logger.info("FluNet fetch complete", total_records=len(normalized))
        return normalized

    def _parse_entry(self, entry: dict) -> list[FluCaseRecord]:
        """Parse a single FluNet OData entry into FluCaseRecords."""
        country_code = (entry.get("ISO2") or "").strip().upper()
        if country_code in UK_COMPONENT_TO_GB:
            country_code = "GB"
        if not country_code:
            return []
        if self.target_countries and country_code not in self.target_countries:
            return []

        iso_year = entry.get("ISO_YEAR")
        iso_week = entry.get("ISO_WEEK")
        if not (iso_year and iso_week):
            return []

        try:
            week_date = datetime.strptime(
                f"{iso_year}-W{int(iso_week):02d}-1", "%G-W%V-%u"
            ).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return []

        records = []
        has_specific = False

        # Try specific subtypes first
        for field, flu_type in SPECIFIC_SUBTYPES.items():
            count = entry.get(field)
            if count and int(count) > 0:
                has_specific = True
                records.append(FluCaseRecord(
                    time=week_date,
                    country_code=country_code,
                    new_cases=int(count),
                    flu_type=flu_type,
                    source=self.source_name,
                ))

        # Only use aggregate INF_A/INF_B if no specific subtypes were found
        if not has_specific:
            for field, flu_type in AGGREGATE_SUBTYPES.items():
                count = entry.get(field)
                if count and int(count) > 0:
                    records.append(FluCaseRecord(
                        time=week_date,
                        country_code=country_code,
                        new_cases=int(count),
                        flu_type=flu_type,
                        source=self.source_name,
                    ))

        # Last resort: total positive count
        if not records:
            total_pos = entry.get("INF_ALL") or entry.get("ALL_INF") or 0
            if int(total_pos) > 0:
                records.append(FluCaseRecord(
                    time=week_date,
                    country_code=country_code,
                    new_cases=int(total_pos),
                    flu_type="unknown",
                    source=self.source_name,
                ))

        return records
