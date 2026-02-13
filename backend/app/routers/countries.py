from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import Country, FluCase
from backend.app.schemas import CountryOut, SummaryOut
from backend.app.country_metadata import COUNTRY_META
from backend.app import cache

router = APIRouter(tags=["countries"])


def _country_info(code: str, db_countries: dict[str, Country]) -> dict | None:
    """Get country metadata from DB seed table, falling back to static mapping."""
    if code in db_countries:
        c = db_countries[code]
        return {"name": c.name, "continent": c.continent, "population": c.population, "last_scraped": c.last_scraped}
    if code in COUNTRY_META:
        m = COUNTRY_META[code]
        return {"name": m["name"], "continent": m["continent"], "population": m["population"], "last_scraped": None}
    # Keep countries that have data even when metadata mapping is missing.
    return {"name": code, "continent": None, "population": None, "last_scraped": None}


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(
    continent: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"countries:{continent or 'all'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    week_ago = anchor - timedelta(days=7)
    prior_year_start = week_ago - timedelta(weeks=52)
    prior_year_end = anchor - timedelta(weeks=52)

    # Get all country codes that have data
    codes_result = await db.execute(select(distinct(FluCase.country_code)))
    data_codes = {r[0] for r in codes_result.all()}

    # Get DB seed countries for metadata
    db_result = await db.execute(select(Country))
    db_countries = {c.code: c for c in db_result.scalars().all()}

    # Get 7-day case totals per country
    cases_7d = (
        select(
            FluCase.country_code,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(FluCase.time >= week_ago)
        .group_by(FluCase.country_code)
    )
    result_7d = await db.execute(cases_7d)
    totals_7d = {r.country_code: r.total for r in result_7d.all()}

    # Get prior-year 7-day totals for year-over-year difference
    cases_prior_year = (
        select(
            FluCase.country_code,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(and_(FluCase.time >= prior_year_start, FluCase.time < prior_year_end))
        .group_by(FluCase.country_code)
    )
    result_prior_year = await db.execute(cases_prior_year)
    totals_prior_year = {r.country_code: r.total for r in result_prior_year.all()}

    out = []
    for code in sorted(data_codes):
        info = _country_info(code, db_countries)
        if continent and info["continent"] != continent:
            continue
        recent = totals_7d.get(code, 0)
        prior_year = totals_prior_year.get(code, 0)
        prior_year_diff = recent - prior_year
        trend = ((recent - prior_year) / prior_year * 100) if prior_year else 0.0
        out.append(CountryOut(
            code=code,
            name=info["name"],
            population=info["population"],
            continent=info["continent"],
            last_scraped=info["last_scraped"],
            total_recent_cases=recent,
            prior_year_diff=prior_year_diff,
            trend_pct=round(trend, 1),
        ))
    out.sort(key=lambda c: c.name)
    cache.put(cache_key, out)
    return out


@router.get("/countries/with-regions", response_model=list[str])
async def countries_with_regions(db: AsyncSession = Depends(get_db)):
    """Return country codes that have region-level data."""
    cached = cache.get("countries_with_regions")
    if cached is not None:
        return cached
    result = await db.execute(
        select(distinct(FluCase.country_code)).where(FluCase.region.isnot(None))
    )
    out = sorted(r[0] for r in result.all())
    cache.put("countries_with_regions", out, ttl=3600)
    return out


@router.get("/summary", response_model=SummaryOut)
async def get_summary(db: AsyncSession = Depends(get_db)):
    cached = cache.get("summary")
    if cached is not None:
        return cached
    now = datetime.utcnow()
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or now
    week_ago = anchor - timedelta(days=7)
    four_weeks_ago = anchor - timedelta(days=28)
    two_weeks_ago = anchor - timedelta(days=14)

    # Total countries with data
    country_count = await db.execute(
        select(func.count(distinct(FluCase.country_code)))
    )
    total_countries = country_count.scalar() or 0

    # 7-day total
    q7 = select(func.coalesce(func.sum(FluCase.new_cases), 0)).where(FluCase.time >= week_ago)
    total_7d = (await db.execute(q7)).scalar()

    # 28-day total
    q28 = select(func.coalesce(func.sum(FluCase.new_cases), 0)).where(FluCase.time >= four_weeks_ago)
    total_28d = (await db.execute(q28)).scalar()

    # Global trend
    q_prev = select(func.coalesce(func.sum(FluCase.new_cases), 0)).where(
        and_(FluCase.time >= two_weeks_ago, FluCase.time < week_ago)
    )
    prev_7d = (await db.execute(q_prev)).scalar()
    global_trend = ((total_7d - prev_7d) / prev_7d * 100) if prev_7d else 0.0

    # Top 5 countries by recent cases
    top_q = (
        select(FluCase.country_code, func.sum(FluCase.new_cases).label("total"))
        .where(FluCase.time >= week_ago)
        .group_by(FluCase.country_code)
        .order_by(func.sum(FluCase.new_cases).desc())
        .limit(5)
    )
    top_result = await db.execute(top_q)
    top_rows = top_result.all()

    # Fetch country details for top countries (DB seed table + static fallback)
    db_result = await db.execute(select(Country))
    db_countries = {c.code: c for c in db_result.scalars().all()}
    top_countries = []
    for row in top_rows:
        info = _country_info(row.country_code, db_countries)
        if info:
            top_countries.append(CountryOut(
                code=row.country_code,
                name=info["name"],
                population=info["population"],
                continent=info["continent"],
                total_recent_cases=row.total,
            ))

    # Dominant global flu type
    type_q = (
        select(FluCase.flu_type, func.sum(FluCase.new_cases).label("total"))
        .where(and_(FluCase.time >= week_ago, FluCase.flu_type.isnot(None)))
        .group_by(FluCase.flu_type)
        .order_by(func.sum(FluCase.new_cases).desc())
        .limit(1)
    )
    type_result = await db.execute(type_q)
    type_row = type_result.first()
    dominant_type = type_row.flu_type if type_row else None

    # Active anomalies count
    from backend.app.models import Anomaly
    anomaly_q = select(func.count()).select_from(Anomaly).where(
        Anomaly.detected_at >= week_ago
    )
    active_anomalies = (await db.execute(anomaly_q)).scalar() or 0

    result = SummaryOut(
        total_countries_tracked=total_countries,
        total_cases_7d=total_7d,
        total_cases_28d=total_28d,
        global_trend_pct=round(global_trend, 1),
        top_countries=top_countries,
        active_anomalies=active_anomalies,
        dominant_global_flu_type=dominant_type,
        last_updated=now,
    )
    cache.put("summary", result)
    return result
