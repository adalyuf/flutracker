"""Tests for aggregation service."""

import asyncio
from datetime import datetime, timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import FluCase
from backend.app.services.aggregation import get_rolling_average, get_total_cases


@pytest.mark.asyncio
class TestAggregationService:
    async def test_get_rolling_average_empty(self, db_session: AsyncSession):
        # No data -> empty result
        result = await get_rolling_average(db_session, country_code="US", window_days=7, periods=4)
        assert result == []

    async def test_get_rolling_average_basic(self, db_session: AsyncSession):
        # Seed simple daily data for US across 10 days
        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for i, v in enumerate(values):
            db_session.add(FluCase(
                time=now - timedelta(days=(len(values) - 1 - i)),
                country_code="US",
                new_cases=v,
                source="test",
            ))
        await db_session.commit()

        # 3-day window rolling average should compute correctly per day
        result = await get_rolling_average(db_session, country_code="US", window_days=3, periods=10)
        # expect 10 points
        assert len(result) == 10
        # Check last few rolling averages
        # last value average of [80, 90, 100] = 90
        assert abs(result[-1][1] - 90.0) < 1e-6
        # previous value average of [70, 80, 90] = 80
        assert abs(result[-2][1] - 80.0) < 1e-6

    async def test_get_rolling_average_respects_country(self, db_session: AsyncSession):
        now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        # Seed US and GB data on same days
        for i in range(5):
            t = now - timedelta(days=4 - i)
            db_session.add(FluCase(time=t, country_code="US", new_cases=100 + i * 10, source="test"))
            db_session.add(FluCase(time=t, country_code="GB", new_cases=500, source="test"))
        await db_session.commit()

        res_us = await get_rolling_average(db_session, country_code="US", window_days=2, periods=5)
        res_gb = await get_rolling_average(db_session, country_code="GB", window_days=2, periods=5)
        assert len(res_us) == 5 and len(res_gb) == 5
        # Ensure the averages differ between countries
        assert res_us[-1][1] != res_gb[-1][1]

    async def test_get_total_cases_global_and_country(self, db_session: AsyncSession):
        now = datetime.utcnow()
        # Seed some recent and old data
        recent = now - timedelta(days=3)
        old = now - timedelta(days=30)
        # Recent counts should be included for default days=7
        db_session.add(FluCase(time=recent, country_code="US", new_cases=100, source="test"))
        db_session.add(FluCase(time=recent, country_code="GB", new_cases=50, source="test"))
        # Old data should be excluded
        db_session.add(FluCase(time=old, country_code="US", new_cases=1000, source="test"))
        await db_session.commit()

        total_7d = await get_total_cases(db_session)
        assert total_7d == 150

        total_us = await get_total_cases(db_session, country_code="US")
        assert total_us == 100

    async def test_get_total_cases_zero_when_none(self, db_session: AsyncSession):
        # No rows in period returns 0
        total = await get_total_cases(db_session, country_code="BR", days=14)
        assert total == 0
