from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import FluCase, Country
from backend.app.schemas import SeverityOut
from backend.app import cache

router = APIRouter(tags=["severity"])


@router.get("/severity", response_model=list[SeverityOut])
async def get_severity_index(db: AsyncSession = Depends(get_db)):
    """Compute composite severity index for all countries."""
    cached = cache.get("severity")
    if cached is not None:
        return cached
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    week_ago = anchor - timedelta(days=7)
    two_weeks_ago = anchor - timedelta(days=14)

    # Get all countries
    countries_result = await db.execute(select(Country))
    countries = {c.code: c for c in countries_result.scalars().all()}

    # Current week cases
    current_q = (
        select(FluCase.country_code, func.sum(FluCase.new_cases).label("total"))
        .where(FluCase.time >= week_ago)
        .group_by(FluCase.country_code)
    )
    current_result = await db.execute(current_q)
    current_cases = {r.country_code: r.total for r in current_result.all()}

    # Previous week cases
    prev_q = (
        select(FluCase.country_code, func.sum(FluCase.new_cases).label("total"))
        .where(and_(FluCase.time >= two_weeks_ago, FluCase.time < week_ago))
        .group_by(FluCase.country_code)
    )
    prev_result = await db.execute(prev_q)
    prev_cases = {r.country_code: r.total for r in prev_result.all()}

    # Dominant flu type in the current week per country
    type_q = (
        select(
            FluCase.country_code,
            FluCase.flu_type,
            func.sum(FluCase.new_cases).label("type_total"),
        )
        .where(and_(FluCase.time >= week_ago, FluCase.flu_type.isnot(None)))
        .group_by(FluCase.country_code, FluCase.flu_type)
    )
    type_result = await db.execute(type_q)
    dominant_types: dict[str, str] = {}
    type_max: dict[str, int] = {}
    for row in type_result.all():
        if row.country_code not in type_max or row.type_total > type_max[row.country_code]:
            type_max[row.country_code] = row.type_total
            dominant_types[row.country_code] = row.flu_type

    results = []
    for code, country in countries.items():
        current = current_cases.get(code, 0)
        prev = prev_cases.get(code, 0)
        if not country.population:
            continue

        pop = country.population
        # Component 1: Cases per 100k (0-100 scale, capped at 100)
        rate_per_100k = current / pop * 100_000
        rate_score = min(rate_per_100k / 50 * 100, 100)  # 50 per 100k = max score

        # Component 2: Week-over-week growth rate
        if prev > 0:
            growth = (current - prev) / prev
        else:
            growth = 1.0 if current > 0 else 0.0
        growth_score = min(max(growth * 50 + 50, 0), 100)  # 0% growth = 50, 100% growth = 100

        # Composite severity (weighted)
        score = round(rate_score * 0.55 + growth_score * 0.45, 1)

        # Severity level
        if score >= 80:
            level = "critical"
        elif score >= 60:
            level = "very_high"
        elif score >= 40:
            level = "high"
        elif score >= 20:
            level = "moderate"
        else:
            level = "low"

        results.append(SeverityOut(
            country_code=code,
            country_name=country.name,
            score=score,
            components={
                "rate_per_100k": round(rate_per_100k, 2),
                "rate_score": round(rate_score, 1),
                "growth_pct": round(growth * 100, 1) if prev > 0 else 0,
                "growth_score": round(growth_score, 1),
                "dominant_type": dominant_types.get(code),
            },
            level=level,
        ))

    results.sort(key=lambda x: x.score, reverse=True)
    cache.put("severity", results)
    return results
