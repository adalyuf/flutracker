"""Base scraper abstraction for flu data ingestion."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import FluCase, Country, ScrapeLog

logger = structlog.get_logger()


@dataclass
class FluCaseRecord:
    """Normalized flu case record from any scraper."""
    time: datetime
    country_code: str
    region: Optional[str] = None
    city: Optional[str] = None
    new_cases: int = 0
    flu_type: Optional[str] = None
    source: str = ""


class BaseScraper(ABC):
    """Abstract base class for all flu data scrapers."""

    country_code: str = ""
    source_name: str = ""
    base_url: str = ""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "FluTracker/1.0 (Public Health Research)"},
        )

    @abstractmethod
    async def fetch_latest(self) -> list[FluCaseRecord]:
        """Fetch the latest flu data. Must be implemented by each scraper."""
        ...

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def _get(self, url: str, **kwargs) -> httpx.Response:
        """HTTP GET with automatic retries."""
        response = await self.client.get(url, **kwargs)
        response.raise_for_status()
        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
    )
    async def _post(self, url: str, **kwargs) -> httpx.Response:
        """HTTP POST with automatic retries."""
        response = await self.client.post(url, **kwargs)
        response.raise_for_status()
        return response

    async def run(self, db: AsyncSession) -> int:
        """Execute the scraper: fetch, deduplicate, store. Returns record count."""
        log_entry = ScrapeLog(
            scraper_id=self.source_name,
            started_at=datetime.utcnow(),
            status="running",
        )
        db.add(log_entry)
        await db.flush()

        try:
            records = await self.fetch_latest()
            logger.info(
                "Scraper fetched records",
                scraper=self.source_name,
                count=len(records),
            )

            deduplicated = await self._deduplicate(db, records)
            stored = await self._store(db, deduplicated)

            # Update country last_scraped
            await self._update_last_scraped(db)

            log_entry.status = "success"
            log_entry.records_fetched = stored
            log_entry.finished_at = datetime.utcnow()
            await db.commit()

            logger.info(
                "Scraper completed",
                scraper=self.source_name,
                stored=stored,
            )
            return stored

        except Exception as e:
            log_entry.status = "error"
            log_entry.error_message = str(e)[:500]
            log_entry.finished_at = datetime.utcnow()
            await db.commit()

            logger.error(
                "Scraper failed",
                scraper=self.source_name,
                error=str(e),
            )
            raise

    async def _deduplicate(
        self, db: AsyncSession, records: list[FluCaseRecord]
    ) -> list[FluCaseRecord]:
        """Remove records that already exist in the database."""
        unique = []
        for r in records:
            # Check if this exact data point already exists
            query = select(FluCase).where(and_(
                FluCase.time == r.time,
                FluCase.country_code == r.country_code,
                FluCase.source == r.source,
                FluCase.region == r.region if r.region else FluCase.region.is_(None),
            )).limit(1)
            result = await db.execute(query)
            if not result.scalar_one_or_none():
                unique.append(r)
        return unique

    async def _store(self, db: AsyncSession, records: list[FluCaseRecord]) -> int:
        """Store records in the database."""
        for r in records:
            case = FluCase(
                time=r.time,
                country_code=r.country_code,
                region=r.region,
                city=r.city,
                new_cases=r.new_cases,
                flu_type=r.flu_type,
                source=r.source,
            )
            db.add(case)
        return len(records)

    async def _update_last_scraped(self, db: AsyncSession):
        """Update the last_scraped timestamp for this scraper's country."""
        if self.country_code:
            result = await db.execute(
                select(Country).where(Country.code == self.country_code)
            )
            country = result.scalar_one_or_none()
            if country:
                country.last_scraped = datetime.utcnow()

    async def close(self):
        await self.client.aclose()
