"""Aggregation utilities for time-series flu data."""

from datetime import datetime, timedelta
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import FluCase


async def get_rolling_average(
    db: AsyncSession,
    country_code: str,
    window_days: int = 7,
    periods: int = 12,
) -> list[tuple[datetime, float]]:
    """Get rolling average of cases for a country."""
    since = datetime.utcnow() - timedelta(days=window_days * periods)

    query = (
        select(
            func.date_trunc("day", FluCase.time).label("day"),
            func.sum(FluCase.new_cases).label("cases"),
        )
        .where(and_(FluCase.country_code == country_code, FluCase.time >= since))
        .group_by("day")
        .order_by("day")
    )
    result = await db.execute(query)
    rows = result.all()

    if not rows:
        return []

    # Compute rolling average
    daily_cases = [(r.day, float(r.cases)) for r in rows]
    rolling = []
    for i in range(len(daily_cases)):
        window_start = max(0, i - window_days + 1)
        window = daily_cases[window_start:i + 1]
        avg = sum(v for _, v in window) / len(window)
        rolling.append((daily_cases[i][0], avg))

    return rolling


async def get_total_cases(
    db: AsyncSession,
    country_code: str | None = None,
    days: int = 7,
) -> int:
    """Get total cases in the given period."""
    since = datetime.utcnow() - timedelta(days=days)
    query = select(func.coalesce(func.sum(FluCase.new_cases), 0)).where(FluCase.time >= since)
    if country_code:
        query = query.where(FluCase.country_code == country_code)
    result = await db.execute(query)
    return result.scalar() or 0
