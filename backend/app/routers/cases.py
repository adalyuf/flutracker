from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import FluCase, Region
from backend.app.schemas import CaseOut, CasesByRegionOut, RegionCases, FluTypesOut, FluTypeBreakdown

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[CaseOut])
async def get_cases(
    country: str | None = None,
    region: str | None = None,
    flu_type: str | None = None,
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(FluCase).order_by(FluCase.time.desc())
    if country:
        query = query.where(FluCase.country_code == country.upper())
    if region:
        query = query.where(FluCase.region == region)
    if flu_type:
        query = query.where(FluCase.flu_type == flu_type)
    if from_date:
        query = query.where(FluCase.time >= from_date)
    if to_date:
        query = query.where(FluCase.time <= to_date)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/cases/by-region", response_model=CasesByRegionOut)
async def get_cases_by_region(
    country: str,
    days: int = Query(7, le=90),
    db: AsyncSession = Depends(get_db),
):
    country = country.upper()

    # Use anchor-date pattern
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    since = anchor - timedelta(days=days)
    prev_since = anchor - timedelta(days=days * 2)

    # Aggregate cases by region (current period)
    query = (
        select(
            FluCase.region,
            func.sum(FluCase.new_cases).label("total_cases"),
        )
        .where(and_(FluCase.country_code == country, FluCase.time >= since, FluCase.region.isnot(None)))
        .group_by(FluCase.region)
        .order_by(func.sum(FluCase.new_cases).desc())
    )
    result = await db.execute(query)
    rows = result.all()

    # Aggregate cases by region (previous period for trend)
    prev_query = (
        select(
            FluCase.region,
            func.sum(FluCase.new_cases).label("total_cases"),
        )
        .where(and_(
            FluCase.country_code == country,
            FluCase.time >= prev_since,
            FluCase.time < since,
            FluCase.region.isnot(None),
        ))
        .group_by(FluCase.region)
    )
    prev_result = await db.execute(prev_query)
    prev_totals = {r.region: r.total_cases for r in prev_result.all()}

    # Get region coordinates and population
    region_query = select(Region).where(Region.country_code == country)
    region_result = await db.execute(region_query)
    region_map = {r.name: r for r in region_result.scalars().all()}

    # Get flu type breakdown per region
    type_query = (
        select(
            FluCase.region,
            FluCase.flu_type,
            func.sum(FluCase.new_cases).label("type_cases"),
        )
        .where(and_(FluCase.country_code == country, FluCase.time >= since, FluCase.region.isnot(None)))
        .group_by(FluCase.region, FluCase.flu_type)
    )
    type_result = await db.execute(type_query)
    type_rows = type_result.all()

    # Build type map
    type_map: dict[str, dict[str, int]] = {}
    for row in type_rows:
        if row.region not in type_map:
            type_map[row.region] = {}
        if row.flu_type:
            type_map[row.region][row.flu_type] = row.type_cases

    regions = []
    for row in rows:
        reg = region_map.get(row.region)
        prev = prev_totals.get(row.region, 0)
        trend = round((row.total_cases - prev) / prev * 100, 1) if prev else None
        regions.append(RegionCases(
            region=row.region,
            total_cases=row.total_cases,
            flu_types=type_map.get(row.region, {}),
            lat=reg.lat if reg else None,
            lon=reg.lon if reg else None,
            trend_pct=trend,
            population=reg.population if reg else None,
        ))

    return CasesByRegionOut(country_code=country, period_days=days, regions=regions)


@router.get("/cases/by-city", response_model=list[CaseOut])
async def get_cases_by_city(
    country: str,
    region: str,
    days: int = Query(7, le=90),
    db: AsyncSession = Depends(get_db),
):
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    since = anchor - timedelta(days=days)
    query = (
        select(FluCase)
        .where(and_(
            FluCase.country_code == country.upper(),
            FluCase.region == region,
            FluCase.city.isnot(None),
            FluCase.time >= since,
        ))
        .order_by(FluCase.time.desc())
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/flu-types", response_model=FluTypesOut)
async def get_flu_types(
    country: str | None = None,
    days: int = Query(28, le=365),
    db: AsyncSession = Depends(get_db),
):
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    since = anchor - timedelta(days=days)
    query = (
        select(
            FluCase.flu_type,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(and_(FluCase.time >= since, FluCase.flu_type.isnot(None)))
        .group_by(FluCase.flu_type)
        .order_by(func.sum(FluCase.new_cases).desc())
    )
    if country:
        query = query.where(FluCase.country_code == country.upper())
    result = await db.execute(query)
    rows = result.all()

    grand_total = sum(r.total for r in rows) or 1
    breakdown = [
        FluTypeBreakdown(
            flu_type=r.flu_type,
            count=r.total,
            percentage=round(r.total / grand_total * 100, 1),
        )
        for r in rows
    ]
    return FluTypesOut(
        country_code=country.upper() if country else None,
        period_days=days,
        breakdown=breakdown,
    )
