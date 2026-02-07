from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import FluCase, Country
from backend.app.schemas import (
    TrendOut, TrendPoint, ComparisonOut,
    SeasonData, HistoricalSeasonsOut,
)

router = APIRouter(tags=["trends"])


def _bucket_expression(granularity: str):
    """Return a SQL expression for time bucketing."""
    if granularity == "day":
        return func.date_trunc("day", FluCase.time)
    elif granularity == "week":
        return func.date_trunc("week", FluCase.time)
    else:
        return func.date_trunc("month", FluCase.time)


def _season_label(start_year: int) -> str:
    """Return a season label like '2023-24' for the season starting in Oct of start_year."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _season_boundaries(reference_date: datetime) -> tuple[datetime, datetime]:
    """Return (start, end) of the flu season containing reference_date.

    Flu season: Oct 1 → Sep 30.
    """
    if reference_date.month >= 10:
        start = datetime(reference_date.year, 10, 1)
        end = datetime(reference_date.year + 1, 9, 30, 23, 59, 59)
    else:
        start = datetime(reference_date.year - 1, 10, 1)
        end = datetime(reference_date.year, 9, 30, 23, 59, 59)
    return start, end


@router.get("/trends/historical-seasons", response_model=HistoricalSeasonsOut)
async def get_historical_seasons(
    country: str | None = Query(None),
    seasons: int = Query(5, ge=1, le=10),
    db: AsyncSession = Depends(get_db),
):
    """Return current + past flu seasons with weekly case data."""
    now = datetime.utcnow()
    current_start, current_end = _season_boundaries(now)
    country_upper = country.upper() if country else None

    all_seasons: list[SeasonData] = []

    for i in range(seasons + 1):  # 0 = current season, 1..N = past
        s_start = datetime(current_start.year - i, 10, 1)
        s_end = datetime(current_start.year - i + 1, 9, 30, 23, 59, 59)
        # Clamp future end to now
        if s_end > now:
            s_end = now

        bucket = func.date_trunc("week", FluCase.time)
        filters = [FluCase.time >= s_start, FluCase.time <= s_end]
        if country_upper:
            filters.append(FluCase.country_code == country_upper)

        query = (
            select(bucket.label("bucket"), func.sum(FluCase.new_cases).label("cases"))
            .where(and_(*filters))
            .group_by("bucket")
            .order_by("bucket")
        )
        result = await db.execute(query)
        rows = result.all()

        # Convert to week-of-season index (week 0 = first week of Oct)
        s_start_aware = s_start.replace(tzinfo=timezone.utc)
        data = []
        for row in rows:
            bucket_dt = row.bucket.replace(tzinfo=timezone.utc) if row.bucket.tzinfo is None else row.bucket
            week_offset = int((bucket_dt - s_start_aware).days // 7)
            data.append(TrendPoint(
                date=str(week_offset),
                cases=row.cases,
            ))

        label = _season_label(s_start.year)
        all_seasons.append(SeasonData(label=label, data=data))

    current_season = all_seasons[0] if all_seasons else SeasonData(label="", data=[])
    past_seasons = all_seasons[1:] if len(all_seasons) > 1 else []

    return HistoricalSeasonsOut(
        country_code=country_upper,
        current_season=current_season,
        past_seasons=past_seasons,
    )


@router.get("/trends", response_model=TrendOut)
async def get_trends(
    country: str,
    granularity: str = Query("week", pattern="^(day|week|month)$"),
    weeks: int = Query(12, le=104),
    db: AsyncSession = Depends(get_db),
):
    country = country.upper()
    since = datetime.utcnow() - timedelta(weeks=weeks)
    bucket = _bucket_expression(granularity)

    # Get population for per-100k calculation
    c_result = await db.execute(select(Country).where(Country.code == country))
    country_obj = c_result.scalar_one_or_none()
    pop = country_obj.population if country_obj else None

    query = (
        select(bucket.label("bucket"), func.sum(FluCase.new_cases).label("cases"))
        .where(and_(FluCase.country_code == country, FluCase.time >= since))
        .group_by("bucket")
        .order_by("bucket")
    )
    result = await db.execute(query)
    rows = result.all()

    data = []
    for row in rows:
        per_100k = round(row.cases / pop * 100_000, 2) if pop else None
        data.append(TrendPoint(
            date=row.bucket.strftime("%Y-%m-%d"),
            cases=row.cases,
            cases_per_100k=per_100k,
        ))

    return TrendOut(country_code=country, granularity=granularity, data=data)


@router.get("/trends/global", response_model=TrendOut)
async def get_global_trends(
    granularity: str = Query("week", pattern="^(day|week|month)$"),
    weeks: int = Query(12, le=104),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(weeks=weeks)
    bucket = _bucket_expression(granularity)

    query = (
        select(bucket.label("bucket"), func.sum(FluCase.new_cases).label("cases"))
        .where(FluCase.time >= since)
        .group_by("bucket")
        .order_by("bucket")
    )
    result = await db.execute(query)
    rows = result.all()

    data = [
        TrendPoint(date=row.bucket.strftime("%Y-%m-%d"), cases=row.cases)
        for row in rows
    ]
    return TrendOut(country_code=None, granularity=granularity, data=data)


@router.get("/trends/compare", response_model=ComparisonOut)
async def compare_trends(
    countries: str = Query(..., description="Comma-separated country codes, e.g. US,GB,BR"),
    granularity: str = Query("week", pattern="^(day|week|month)$"),
    weeks: int = Query(12, le=104),
    normalize: bool = Query(True, description="Normalize to cases per 100k"),
    db: AsyncSession = Depends(get_db),
):
    codes = [c.strip().upper() for c in countries.split(",")][:5]
    since = datetime.utcnow() - timedelta(weeks=weeks)
    bucket = _bucket_expression(granularity)

    # Get populations
    pop_result = await db.execute(select(Country).where(Country.code.in_(codes)))
    pop_map = {c.code: c.population for c in pop_result.scalars().all()}

    series = {}
    for code in codes:
        query = (
            select(bucket.label("bucket"), func.sum(FluCase.new_cases).label("cases"))
            .where(and_(FluCase.country_code == code, FluCase.time >= since))
            .group_by("bucket")
            .order_by("bucket")
        )
        result = await db.execute(query)
        rows = result.all()

        pop = pop_map.get(code)
        series[code] = [
            TrendPoint(
                date=row.bucket.strftime("%Y-%m-%d"),
                cases=row.cases,
                cases_per_100k=round(row.cases / pop * 100_000, 2) if (normalize and pop) else None,
            )
            for row in rows
        ]

    return ComparisonOut(granularity=granularity, series=series)
