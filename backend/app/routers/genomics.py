from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import GenomicSequence
from backend.app.schemas import (
    GenomicsCountriesOut,
    GenomicsCountryRow,
    GenomicsSummaryOut,
    GenomicsTrendPoint,
    GenomicsTrendsOut,
)

router = APIRouter(tags=["genomics"])


def _ensure_datetime(value) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


async def _anchor_date(db: AsyncSession) -> datetime:
    anchor = (await db.execute(select(func.max(GenomicSequence.sample_date)))).scalar()
    if anchor is None:
        return datetime.now(timezone.utc)
    return anchor


@router.get("/genomics/summary", response_model=GenomicsSummaryOut)
async def genomics_summary(
    years: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    anchor = await _anchor_date(db)
    since = anchor - timedelta(days=365 * years)

    filters = [GenomicSequence.sample_date >= since]
    stats_query = select(
        func.count().label("total_sequences"),
        func.count(func.distinct(GenomicSequence.country_code)).label("countries_tracked"),
        func.count(func.distinct(GenomicSequence.clade)).label("unique_clades"),
        func.min(GenomicSequence.sample_date).label("start_date"),
        func.max(GenomicSequence.sample_date).label("end_date"),
        func.max(GenomicSequence.inserted_at).label("last_updated"),
    ).where(and_(*filters))
    stats = (await db.execute(stats_query)).one()

    dominant_query = (
        select(
            GenomicSequence.clade,
            func.count().label("n"),
        )
        .where(and_(*filters, GenomicSequence.clade.isnot(None)))
        .group_by(GenomicSequence.clade)
        .order_by(func.count().desc())
        .limit(1)
    )
    dominant = (await db.execute(dominant_query)).first()

    return GenomicsSummaryOut(
        total_sequences=stats.total_sequences or 0,
        countries_tracked=stats.countries_tracked or 0,
        unique_clades=stats.unique_clades or 0,
        dominant_clade=dominant.clade if dominant else None,
        start_date=_ensure_datetime(stats.start_date) if stats.start_date else None,
        end_date=_ensure_datetime(stats.end_date) if stats.end_date else None,
        last_updated=_ensure_datetime(stats.last_updated) if stats.last_updated else None,
    )


@router.get("/genomics/trends", response_model=GenomicsTrendsOut)
async def genomics_trends(
    country: str | None = Query(None),
    years: int = Query(10, ge=1, le=20),
    top_n: int = Query(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    anchor = await _anchor_date(db)
    since = anchor - timedelta(days=365 * years)

    filters = [GenomicSequence.sample_date >= since]
    country_upper = country.upper() if country else None
    if country_upper:
        filters.append(GenomicSequence.country_code == country_upper)

    bucket = func.date_trunc("month", GenomicSequence.sample_date)
    query = (
        select(
            bucket.label("month"),
            GenomicSequence.clade,
            func.count().label("n"),
        )
        .where(and_(*filters))
        .group_by("month", GenomicSequence.clade)
        .order_by("month")
    )
    rows = (await db.execute(query)).all()

    if not rows:
        return GenomicsTrendsOut(country_code=country_upper, years=years, top_clades=[], data=[])

    totals: dict[str, int] = {}
    for r in rows:
        clade = r.clade or "Unknown"
        totals[clade] = totals.get(clade, 0) + int(r.n)

    top_clades = [k for k, _ in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:top_n]]
    output: dict[tuple[str, str], int] = {}
    for r in rows:
        month_dt = _ensure_datetime(r.month)
        month_key = month_dt.strftime("%Y-%m-01")
        clade = r.clade or "Unknown"
        clade_key = clade if clade in top_clades else "Other"
        key = (month_key, clade_key)
        output[key] = output.get(key, 0) + int(r.n)

    points = [
        GenomicsTrendPoint(month=month, clade=clade, sequences=n)
        for (month, clade), n in sorted(output.items(), key=lambda x: x[0][0])
    ]
    return GenomicsTrendsOut(
        country_code=country_upper,
        years=years,
        top_clades=top_clades,
        data=points,
    )


@router.get("/genomics/countries", response_model=GenomicsCountriesOut)
async def genomics_countries(
    years: int = Query(10, ge=1, le=20),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    anchor = await _anchor_date(db)
    since = anchor - timedelta(days=365 * years)

    query = (
        select(
            GenomicSequence.country_code,
            GenomicSequence.country_name,
            func.count().label("sequences"),
            func.count(func.distinct(GenomicSequence.clade)).label("unique_clades"),
            func.max(GenomicSequence.sample_date).label("last_sample_date"),
        )
        .where(
            and_(
                GenomicSequence.sample_date >= since,
                GenomicSequence.country_code.isnot(None),
            )
        )
        .group_by(GenomicSequence.country_code, GenomicSequence.country_name)
        .order_by(func.count().desc())
        .limit(limit)
    )
    rows = (await db.execute(query)).all()

    countries = [
        GenomicsCountryRow(
            country_code=r.country_code,
            country_name=r.country_name or r.country_code,
            sequences=int(r.sequences),
            unique_clades=int(r.unique_clades or 0),
            last_sample_date=_ensure_datetime(r.last_sample_date) if r.last_sample_date else None,
        )
        for r in rows
    ]
    return GenomicsCountriesOut(years=years, countries=countries)
