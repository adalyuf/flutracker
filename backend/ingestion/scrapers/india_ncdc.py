"""
India NCDC/IDSP scraper — Integrated Disease Surveillance Programme.

Data source: National Centre for Disease Control (NCDC)
https://ncdc.mohfw.gov.in/
Provides national and some state-level influenza data.
"""

from datetime import datetime, timedelta

import structlog
from bs4 import BeautifulSoup

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

NCDC_URL = "https://ncdc.mohfw.gov.in/"
IDSP_URL = "https://idsp.mohfw.gov.in/"

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
    "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Delhi", "Jammu and Kashmir", "Ladakh",
]


class IndiaNCScraper(BaseScraper):
    """Scraper for India NCDC/IDSP flu surveillance data."""

    country_code = "IN"
    source_name = "india_ncdc"

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest NCDC flu data."""
        records = []

        # Try IDSP disease outbreak reports
        try:
            records = await self._fetch_idsp_outbreaks()
        except Exception as e:
            logger.warning("IDSP fetch failed", error=str(e))

        # Try NCDC main page for recent data
        if not records:
            try:
                records = await self._scrape_ncdc_page()
            except Exception as e:
                logger.error("NCDC scrape failed", error=str(e))

        return records

    async def _fetch_idsp_outbreaks(self) -> list[FluCaseRecord]:
        """Fetch from IDSP weekly outbreak reports."""
        # IDSP publishes weekly disease outbreak reports
        response = await self._get(f"{IDSP_URL}index4.php?lang=1&level=0&linkid=406&lid=3689")
        soup = BeautifulSoup(response.text, "lxml")

        records = []
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:  # Skip header
                cells = row.find_all("td")
                if len(cells) < 5:
                    continue

                text = [c.get_text(strip=True) for c in cells]

                # Look for influenza/ILI related rows
                disease = text[1].lower() if len(text) > 1 else ""
                if not any(k in disease for k in ["influenza", "ili", "h1n1", "flu"]):
                    continue

                state = text[2] if len(text) > 2 else None
                cases_str = text[3] if len(text) > 3 else "0"

                try:
                    cases = int("".join(c for c in cases_str if c.isdigit()) or "0")
                except ValueError:
                    cases = 0

                if cases > 0:
                    # Determine flu type from disease name
                    flu_type = None
                    if "h1n1" in disease:
                        flu_type = "H1N1"
                    elif "h3n2" in disease:
                        flu_type = "H3N2"

                    records.append(FluCaseRecord(
                        time=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
                        country_code="IN",
                        region=state if state and state in INDIAN_STATES else None,
                        new_cases=cases,
                        flu_type=flu_type,
                        source=self.source_name,
                    ))

        return records

    async def _scrape_ncdc_page(self) -> list[FluCaseRecord]:
        """Scrape NCDC main page for flu-related alerts and data."""
        response = await self._get(NCDC_URL)
        soup = BeautifulSoup(response.text, "lxml")

        records = []

        # Look for flu-related content in alerts, tables, and data sections
        alert_sections = soup.find_all(["div", "section"], class_=lambda c: c and "alert" in str(c).lower())

        for section in alert_sections:
            text = section.get_text()
            if any(k in text.lower() for k in ["influenza", "h1n1", "h3n2", "flu"]):
                # Try to extract numbers from the alert text
                import re
                numbers = re.findall(r"(\d+)\s*(?:cases|patients)", text, re.IGNORECASE)
                for num_str in numbers:
                    cases = int(num_str)
                    if cases > 0:
                        records.append(FluCaseRecord(
                            time=datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
                            country_code="IN",
                            new_cases=cases,
                            flu_type=self._extract_flu_type(text),
                            source=self.source_name,
                        ))

        return records

    @staticmethod
    def _extract_flu_type(text: str) -> str | None:
        text_lower = text.lower()
        if "h1n1" in text_lower:
            return "H1N1"
        elif "h3n2" in text_lower:
            return "H3N2"
        elif "type b" in text_lower or "influenza b" in text_lower:
            return "B (lineage unknown)"
        return None
