"""
UK UKHSA (UK Health Security Agency) scraper.

Data source: UKHSA weekly flu reports and DataMart.
Provides regional breakdown (England regions, Scotland, Wales, Northern Ireland)
and flu subtype information.
"""

from datetime import datetime, timedelta

import structlog
from bs4 import BeautifulSoup

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

# UKHSA DataMart API
DATAMART_API = "https://ukhsa-dashboard.data.gov.uk/api"
SURVEILLANCE_URL = "https://www.gov.uk/government/statistics/national-flu-and-covid-19-surveillance-reports"

UK_REGIONS = [
    "North East", "North West", "Yorkshire and The Humber",
    "East Midlands", "West Midlands", "East of England",
    "London", "South East", "South West",
    "Scotland", "Wales", "Northern Ireland",
]


class UKUKHSAScraper(BaseScraper):
    """Scraper for UKHSA flu surveillance data."""

    country_code = "GB"
    source_name = "uk_ukhsa"

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest UKHSA flu data."""
        records = []

        # Try the UKHSA API first
        try:
            records = await self._fetch_api()
        except Exception as e:
            logger.warning("UKHSA API failed, trying scrape", error=str(e))

        # Fallback: scrape the surveillance report page
        if not records:
            try:
                records = await self._scrape_reports()
            except Exception as e:
                logger.error("UKHSA scrape failed", error=str(e))

        return records

    async def _fetch_api(self) -> list[FluCaseRecord]:
        """Try fetching from the UKHSA dashboard API."""
        # The UKHSA dashboard API provides respiratory surveillance data
        url = f"{DATAMART_API}/themes/infectious_disease/sub_themes/respiratory"
        params = {
            "metric": "influenza_healthcare_ICUHDUadmissionRateByWeek",
            "page_size": 100,
        }

        try:
            response = await self._get(url, params=params)
            data = response.json()
        except Exception:
            # Try alternative endpoint format
            url = "https://api.ukhsa-dashboard.data.gov.uk/themes/infectious_disease/sub_themes/respiratory/topics/influenza/geography_types/Nation/geographies/England/metrics/influenza_testing_positivityByWeek"
            response = await self._get(url, params={"page_size": 52})
            data = response.json()

        records = []
        results = data.get("results", [])

        for entry in results:
            date_str = entry.get("date") or entry.get("metric_value_date")
            value = entry.get("metric_value") or entry.get("value", 0)
            geography = entry.get("geography", "England")

            if not date_str or not value:
                continue

            try:
                date = datetime.strptime(date_str[:10], "%Y-%m-%d")
            except ValueError:
                continue

            records.append(FluCaseRecord(
                time=date,
                country_code="GB",
                region=geography,
                new_cases=int(float(value)),
                source=self.source_name,
            ))

        return records

    async def _scrape_reports(self) -> list[FluCaseRecord]:
        """Scrape weekly surveillance report page for flu data."""
        response = await self._get(SURVEILLANCE_URL)
        soup = BeautifulSoup(response.text, "lxml")

        records = []
        # Look for links to the actual data files (CSV/ODS)
        links = soup.find_all("a", href=True)
        for link in links:
            href = link["href"]
            if "flu" in href.lower() and href.endswith(".csv"):
                try:
                    csv_response = await self._get(href)
                    records.extend(self._parse_csv(csv_response.text))
                except Exception as e:
                    logger.warning("Failed to fetch UKHSA CSV", url=href, error=str(e))

        return records

    def _parse_csv(self, csv_text: str) -> list[FluCaseRecord]:
        """Parse a UKHSA flu surveillance CSV."""
        records = []
        lines = csv_text.strip().split("\n")
        if len(lines) < 2:
            return records

        headers = [h.strip().lower() for h in lines[0].split(",")]

        for line in lines[1:]:
            values = line.split(",")
            if len(values) < len(headers):
                continue
            row = dict(zip(headers, values))

            # Try to extract date, region, case count
            date_str = row.get("week_ending") or row.get("date") or row.get("week")
            region = row.get("region") or row.get("geography") or row.get("phec_name")
            cases = row.get("total_flu") or row.get("influenza_cases") or row.get("count")
            flu_type = row.get("flu_type") or row.get("subtype")

            if not date_str or not cases:
                continue

            try:
                # Try multiple date formats
                for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"]:
                    try:
                        date = datetime.strptime(date_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue

                case_count = int(float(cases.strip()))
                if case_count <= 0:
                    continue
            except (ValueError, AttributeError):
                continue

            records.append(FluCaseRecord(
                time=date,
                country_code="GB",
                region=region.strip() if region else None,
                new_cases=case_count,
                flu_type=flu_type.strip() if flu_type else None,
                source=self.source_name,
            ))

        return records
