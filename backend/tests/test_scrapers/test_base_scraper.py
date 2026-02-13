"""Tests for BaseScraper logic using a concrete stub subclass."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from backend.ingestion.base_scraper import BaseScraper, FluCaseRecord
from backend.app.models import FluCase, ScrapeLog


class StubScraper(BaseScraper):
    country_code = "XX"
    source_name = "test_stub"

    def __init__(self, records=None, should_fail=False):
        super().__init__()
        self._records = records or []
        self._should_fail = should_fail

    async def fetch_latest(self):
        if self._should_fail:
            raise RuntimeError("scrape failed")
        return self._records


def _make_record(time=None, region=None):
    return FluCaseRecord(
        time=time or datetime(2025, 1, 6),
        country_code="XX",
        new_cases=100,
        source="test_stub",
        region=region,
    )


@pytest.mark.asyncio
async def test_deduplicate_filters_existing(db_session):
    """Records already in DB get filtered out by _deduplicate."""
    # Insert an existing record
    db_session.add(FluCase(
        time=datetime(2025, 1, 6),
        country_code="XX",
        new_cases=100,
        source="test_stub",
    ))
    await db_session.flush()

    scraper = StubScraper()
    records = [_make_record(datetime(2025, 1, 6)), _make_record(datetime(2025, 1, 13))]
    result = await scraper._deduplicate(db_session, records)
    assert len(result) == 1
    assert result[0].time == datetime(2025, 1, 13)
    await scraper.close()


@pytest.mark.asyncio
async def test_deduplicate_empty_input(db_session):
    scraper = StubScraper()
    result = await scraper._deduplicate(db_session, [])
    assert result == []
    await scraper.close()


@pytest.mark.asyncio
async def test_store_batches(db_session):
    """Records get persisted to the database via _store."""
    scraper = StubScraper()
    records = [_make_record(datetime(2025, 1, i + 1)) for i in range(5)]
    stored = await scraper._store(db_session, records)
    assert stored == 5

    from sqlalchemy import select, func
    count = (await db_session.execute(
        select(func.count()).select_from(FluCase).where(FluCase.source == "test_stub")
    )).scalar()
    assert count == 5
    await scraper.close()


@pytest.mark.asyncio
async def test_run_logs_success(db_session):
    """Successful run creates a ScrapeLog entry with status='success'."""
    records = [_make_record()]
    scraper = StubScraper(records=records)
    count = await scraper.run(db_session)
    assert count == 1

    from sqlalchemy import select
    log = (await db_session.execute(
        select(ScrapeLog).where(ScrapeLog.scraper_id == "test_stub")
    )).scalar_one()
    assert log.status == "success"
    assert log.records_fetched == 1
    assert log.finished_at is not None
    await scraper.close()


@pytest.mark.asyncio
async def test_run_logs_failure(db_session):
    """Failed run creates a ScrapeLog entry with status='error'."""
    scraper = StubScraper(should_fail=True)
    with pytest.raises(RuntimeError):
        await scraper.run(db_session)

    from sqlalchemy import select
    log = (await db_session.execute(
        select(ScrapeLog).where(ScrapeLog.scraper_id == "test_stub")
    )).scalar_one()
    assert log.status == "error"
    assert "scrape failed" in log.error_message
    await scraper.close()


@pytest.mark.asyncio
async def test_deduplicate_uses_flu_type_and_normalizes_time(db_session):
    """Same week/country/source but different flu_type should not collapse."""
    db_session.add(FluCase(
        time=datetime(2025, 1, 6, tzinfo=timezone.utc),
        country_code="XX",
        new_cases=100,
        flu_type="H1N1",
        source="test_stub",
    ))
    await db_session.flush()

    scraper = StubScraper()
    records = [
        FluCaseRecord(
            time=datetime(2025, 1, 6),  # naive (simulates parser output)
            country_code="XX",
            new_cases=100,
            flu_type="H1N1",
            source="test_stub",
        ),
        FluCaseRecord(
            time=datetime(2025, 1, 6),  # same timestamp, different subtype
            country_code="XX",
            new_cases=50,
            flu_type="H3N2",
            source="test_stub",
        ),
    ]
    result = await scraper._deduplicate(db_session, records)
    assert len(result) == 1
    assert result[0].flu_type == "H3N2"
    await scraper.close()


@pytest.mark.asyncio
async def test_deduplicate_filters_duplicate_records_within_batch(db_session):
    scraper = StubScraper()
    records = [
        FluCaseRecord(
            time=datetime(2025, 1, 6),
            country_code="XX",
            new_cases=100,
            flu_type="H1N1",
            source="test_stub",
        ),
        FluCaseRecord(
            time=datetime(2025, 1, 6),
            country_code="XX",
            new_cases=100,
            flu_type="H1N1",
            source="test_stub",
        ),
    ]
    result = await scraper._deduplicate(db_session, records)
    assert len(result) == 1
    await scraper.close()
