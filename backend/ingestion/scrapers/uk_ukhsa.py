"""
UK UKHSA (UK Health Security Agency) scraper.

Data source: UKHSA Dashboard API (api.ukhsa-dashboard.data.gov.uk)
Provides weekly influenza hospital admission rates and testing positivity
for England (nation-level and by UKHSA region).

API docs: https://ukhsa-dashboard.data.gov.uk/access-our-data/getting-started
Swagger: https://api.ukhsa-dashboard.data.gov.uk/api/swagger/

Notes:
- Page size max is 365.
- API is aggressively rate-limited — needs 8-15s delay between requests.
- Data covers England only (Scotland/Wales/NI have separate systems).
- Hospital admission rate goes back to 2015; positivity to 2017.
- metric_value for admissions is a rate per 100k population.
"""

import asyncio
from datetime import datetime, timedelta

import structlog

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

UKHSA_API_BASE = "https://api.ukhsa-dashboard.data.gov.uk"

# England population for converting rates per 100k to estimated case counts
ENGLAND_POP = 56_500_000

# Metrics to fetch, in priority order
METRICS = [
    {
        "name": "influenza_healthcare_hospitalAdmissionRateByWeek",
        "topic": "Influenza",
        "geo_type": "Nation",
        "geo": "England",
        "flu_type": None,
        "is_rate_per_100k": True,
    },
    {
        "name": "influenza_healthcare_ICUHDUadmissionRateByWeek",
        "topic": "Influenza",
        "geo_type": "Nation",
        "geo": "England",
        "flu_type": None,
        "is_rate_per_100k": True,
    },
]

# Regions to scrape for regional breakdown
UKHSA_REGIONS = [
    "East Midlands", "East of England", "London", "North East",
    "North West", "South East", "South West", "West Midlands",
    "Yorkshire and Humber",
]

# Approximate population per region (2023 ONS mid-year estimates, rounded)
REGION_POP = {
    "East Midlands": 4_900_000,
    "East of England": 6_400_000,
    "London": 8_900_000,
    "North East": 2_700_000,
    "North West": 7_400_000,
    "South East": 9_300_000,
    "South West": 5_700_000,
    "West Midlands": 5_900_000,
    "Yorkshire and Humber": 5_500_000,
}

# Rate limit delay between API requests (seconds)
REQUEST_DELAY = 10


def _build_metric_url(topic: str, geo_type: str, geo: str, metric: str) -> str:
    """Build a UKHSA API URL for a specific metric."""
    geo_type_enc = geo_type.replace(" ", "%20")
    geo_enc = geo.replace(" ", "%20")
    return (
        f"{UKHSA_API_BASE}/themes/infectious_disease/sub_themes/respiratory"
        f"/topics/{topic}/geography_types/{geo_type_enc}"
        f"/geographies/{geo_enc}/metrics/{metric}"
    )


class UKUKHSAScraper(BaseScraper):
    """Scraper for UKHSA flu surveillance data."""

    country_code = "GB"
    source_name = "uk_ukhsa"

    def __init__(self, include_regions: bool = False, delay: float = REQUEST_DELAY):
        super().__init__()
        self.include_regions = include_regions
        self.delay = delay

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest UKHSA flu data (last 8 weeks)."""
        since = datetime.utcnow() - timedelta(weeks=8)
        return await self.fetch_all(since_year=since.year)

    async def fetch_all(self, since_year: int | None = None) -> list[FluCaseRecord]:
        """Fetch all UKHSA flu data, optionally filtered by year."""
        records = []

        # Fetch nation-level hospital admission rate (primary metric)
        nation_records = await self._fetch_metric(
            topic="Influenza",
            geo_type="Nation",
            geo="England",
            metric="influenza_healthcare_hospitalAdmissionRateByWeek",
            population=ENGLAND_POP,
            is_rate_per_100k=True,
            region=None,
            since_year=since_year,
        )
        records.extend(nation_records)

        # Fetch regional hospital admission rates
        if self.include_regions:
            for region in UKHSA_REGIONS:
                pop = REGION_POP.get(region, 5_000_000)
                regional = await self._fetch_metric(
                    topic="Influenza",
                    geo_type="UKHSA Region",
                    geo=region,
                    metric="influenza_healthcare_hospitalAdmissionRateByWeek",
                    population=pop,
                    is_rate_per_100k=True,
                    region=region,
                    since_year=since_year,
                )
                records.extend(regional)

        logger.info("UKHSA fetch complete", total_records=len(records))
        return records

    async def _fetch_metric(
        self,
        topic: str,
        geo_type: str,
        geo: str,
        metric: str,
        population: int,
        is_rate_per_100k: bool,
        region: str | None,
        since_year: int | None = None,
    ) -> list[FluCaseRecord]:
        """Fetch all pages of a single metric, with rate limiting."""
        url = _build_metric_url(topic, geo_type, geo, metric)
        params = {"page_size": 365, "age": "all"}
        if since_year:
            params["year"] = since_year

        records = []
        page = 1

        while True:
            params["page"] = page
            logger.info("UKHSA API request", metric=metric, geo=geo, page=page)

            try:
                response = await self._get(url, params=params)
                text = response.text.strip()
                if not text:
                    # Rate limited — wait and retry once
                    logger.warning("UKHSA empty response (rate limited), retrying",
                                   metric=metric, page=page)
                    await asyncio.sleep(self.delay * 2)
                    response = await self._get(url, params=params)
                    text = response.text.strip()
                    if not text:
                        logger.error("UKHSA still empty after retry", metric=metric)
                        break

                data = response.json()
            except Exception as e:
                logger.error("UKHSA API error", metric=metric, page=page, error=str(e))
                break

            results = data.get("results", [])
            if not results:
                break

            for entry in results:
                record = self._parse_entry(
                    entry, population, is_rate_per_100k, region
                )
                if record:
                    records.append(record)

            # Check for next page
            if not data.get("next"):
                break

            page += 1

            # If not filtering by year, we need to paginate through all data.
            # For year-filtered queries, the count is small enough to not need
            # aggressive pagination.
            if not since_year:
                await asyncio.sleep(self.delay)

        return records

    def _parse_entry(
        self,
        entry: dict,
        population: int,
        is_rate_per_100k: bool,
        region: str | None,
    ) -> FluCaseRecord | None:
        """Parse a single UKHSA API result into a FluCaseRecord."""
        date_str = entry.get("date")
        value = entry.get("metric_value")

        if not date_str or value is None:
            return None

        try:
            date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return None

        # Convert rate per 100k to estimated case count
        if is_rate_per_100k:
            cases = max(0, round(float(value) * population / 100_000))
        else:
            cases = max(0, int(float(value)))

        if cases == 0:
            return None

        return FluCaseRecord(
            time=date,
            country_code="GB",
            region=region,
            new_cases=cases,
            source=self.source_name,
        )
