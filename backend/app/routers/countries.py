from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import Country, FluCase
from backend.app.schemas import CountryOut, SummaryOut

router = APIRouter(tags=["countries"])


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(
    continent: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    week_ago = anchor - timedelta(days=7)
    two_weeks_ago = anchor - timedelta(days=14)

    # Get all countries
    query = select(Country).order_by(Country.name)
    if continent:
        query = query.where(Country.continent == continent)
    result = await db.execute(query)
    countries = result.scalars().all()

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

    # Get previous 7-day totals for trend
    cases_prev = (
        select(
            FluCase.country_code,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(and_(FluCase.time >= two_weeks_ago, FluCase.time < week_ago))
        .group_by(FluCase.country_code)
    )
    result_prev = await db.execute(cases_prev)
    totals_prev = {r.country_code: r.total for r in result_prev.all()}

    out = []
    for c in countries:
        recent = totals_7d.get(c.code, 0)
        prev = totals_prev.get(c.code, 0)
        trend = ((recent - prev) / prev * 100) if prev else 0.0
        out.append(CountryOut(
            code=c.code,
            name=c.name,
            population=c.population,
            continent=c.continent,
            last_scraped=c.last_scraped,
            total_recent_cases=recent,
            trend_pct=round(trend, 1),
        ))
    return out


@router.get("/summary", response_model=SummaryOut)
async def get_summary(db: AsyncSession = Depends(get_db)):
    now = datetime.utcnow()
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or now
    week_ago = anchor - timedelta(days=7)
    four_weeks_ago = anchor - timedelta(days=28)
    two_weeks_ago = anchor - timedelta(days=14)

    # Total countries
    country_count = await db.execute(select(func.count()).select_from(Country))
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

    # Fetch country details for top countries
    top_countries = []
    for row in top_rows:
        c = await db.execute(select(Country).where(Country.code == row.country_code))
        country = c.scalar_one_or_none()
        if country:
            top_countries.append(CountryOut(
                code=country.code,
                name=country.name,
                population=country.population,
                continent=country.continent,
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

    return SummaryOut(
        total_countries_tracked=total_countries,
        total_cases_7d=total_7d,
        total_cases_28d=total_28d,
        global_trend_pct=round(global_trend, 1),
        top_countries=top_countries,
        active_anomalies=active_anomalies,
        dominant_global_flu_type=dominant_type,
        last_updated=now,
    )
