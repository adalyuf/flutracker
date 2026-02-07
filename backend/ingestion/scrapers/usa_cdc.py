"""
USA CDC FluView scraper — state-level flu activity from CDC FluView Phase 1 API.

Data source: CDC FluView Interactive
Init API: https://gis.cdc.gov/grasp/fluView1/Phase1IniP
Download API: https://gis.cdc.gov/grasp/fluView1/Phase1DownloadDataP/{seasonid}
"""

import json
import re
from datetime import datetime

import structlog

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord

logger = structlog.get_logger()

# CDC FluView Phase 1 API endpoints
FLUVIEW_INIT_API = "https://gis.cdc.gov/grasp/fluView1/Phase1IniP"
FLUVIEW_DOWNLOAD_API = "https://gis.cdc.gov/grasp/fluView1/Phase1DownloadDataP/%d"

# Map CDC ILI activity level (0-13) to estimated case counts per 100k.
# CDC levels: 0=Insufficient Data, 1-3=Minimal, 4-5=Low, 6-7=Moderate,
# 8-9=High, 10=High, 11-13=Very High
ACTIVITY_LEVEL_CASE_ESTIMATE = {
    0: 0,
    1: 50, 2: 100, 3: 200,
    4: 400, 5: 600,
    6: 1000, 7: 1500,
    8: 2500, 9: 3500,
    10: 5000, 11: 7000,
    12: 9000, 13: 12000,
}


def _unwrap_cdc_json(text: str) -> dict:
    """Parse CDC API responses that may be wrapped in XML or double-encoded.

    The Phase1 endpoints return JSON in several flavors:
    - XML-wrapped: <string xmlns="...">{"seasons":[...]}</string>
    - Double-encoded JSON string: '"{\"datadownload\":[...]}"'
    - Plain JSON dict (least common)
    """
    body = text.strip()

    # Strip XML <string> wrapper if present
    if body.startswith("<"):
        m = re.search(r">(.+)<", body, re.DOTALL)
        if m:
            body = m.group(1)

    parsed = json.loads(body)

    # Handle double-encoded JSON (string within JSON)
    if isinstance(parsed, str):
        parsed = json.loads(parsed)

    return parsed


class USACDCScraper(BaseScraper):
    """Scraper for CDC FluView surveillance data using Phase 1 API."""

    country_code = "US"
    source_name = "usa_cdc"

    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch latest CDC FluView data with state-level breakdown.

        1. Hit the init endpoint to discover available seasons.
        2. Download data for the most recent season(s).
        """
        try:
            seasons = await self._fetch_seasons()
        except Exception as e:
            logger.error("CDC FluView init API failed", error=str(e))
            return []

        if not seasons:
            logger.warning("No seasons returned from CDC init API")
            return []

        # Fetch the two most recent seasons to capture data near season boundaries
        recent = sorted(seasons, key=lambda s: s["seasonid"], reverse=True)[:2]
        logger.info(
            "CDC FluView downloading seasons",
            seasons=[s["label"] for s in recent],
        )

        records: list[FluCaseRecord] = []
        for season in recent:
            try:
                season_records = await self._fetch_season_data(season["seasonid"])
                records.extend(season_records)
            except Exception as e:
                logger.error(
                    "CDC FluView season download failed",
                    season=season["label"],
                    error=str(e),
                )

        return records

    async def _fetch_seasons(self) -> list[dict]:
        """Fetch available flu seasons from the Phase1 init endpoint.

        Returns list of dicts with keys: seasonid, label, description, etc.
        """
        response = await self._get(FLUVIEW_INIT_API)
        data = _unwrap_cdc_json(response.text)
        seasons = data.get("Seasons", data.get("seasons", []))
        logger.info("CDC FluView found seasons", count=len(seasons))
        return seasons

    async def _fetch_season_data(self, season_id: int) -> list[FluCaseRecord]:
        """Download weekly state-level activity data for a given season.

        The download endpoint returns a JSON string containing:
        {
            "datadownload": [
                {
                    "statename": "Alabama",
                    "activity_level": "13",
                    "activity_level_label": "Very High",
                    "weekend": "Dec-27-2025",
                    "season": "2025-26",
                    "weeknumber": "52",
                    ...
                },
                ...
            ]
        }
        """
        url = FLUVIEW_DOWNLOAD_API % season_id
        response = await self._get(url, timeout=60.0)
        payload = _unwrap_cdc_json(response.text)

        entries = payload.get("datadownload", [])
        logger.info(
            "CDC FluView season data",
            season_id=season_id,
            entries=len(entries),
        )

        records = []
        for entry in entries:
            record = self._parse_entry(entry)
            if record:
                records.append(record)

        return records

    def _parse_entry(self, entry: dict) -> FluCaseRecord | None:
        """Parse a single data download entry into a FluCaseRecord."""
        state = entry.get("statename", "").strip()
        weekend_str = entry.get("weekend", "")
        activity_str = entry.get("activity_level", "0")

        if not state or not weekend_str:
            return None

        try:
            activity_level = int(activity_str)
        except (ValueError, TypeError):
            return None

        # Skip insufficient data
        if activity_level == 0:
            return None

        estimated_cases = ACTIVITY_LEVEL_CASE_ESTIMATE.get(activity_level, 0)
        if estimated_cases <= 0:
            return None

        # Parse weekend date — format: "Dec-27-2025"
        try:
            week_date = datetime.strptime(weekend_str, "%b-%d-%Y")
        except ValueError:
            return None

        return FluCaseRecord(
            time=week_date,
            country_code="US",
            region=state,
            new_cases=estimated_cases,
            flu_type=None,
            source=self.source_name,
        )
