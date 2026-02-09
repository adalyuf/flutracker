import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import FluCase, Country
from backend.app.schemas import MapFeatureProperties

router = APIRouter(tags=["map"])


@router.get("/map/geojson")
async def get_map_geojson(
    period: int = Query(7, description="Days to aggregate", le=90),
    db: AsyncSession = Depends(get_db),
):
    """Return GeoJSON FeatureCollection with per-country flu stats for map coloring."""
    anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or datetime.utcnow()
    since = anchor - timedelta(days=period)
    prev_since = since - timedelta(days=period)

    # Current period cases by country
    current_q = (
        select(
            FluCase.country_code,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(FluCase.time >= since)
        .group_by(FluCase.country_code)
    )
    current_result = await db.execute(current_q)
    current_map = {r.country_code: r.total for r in current_result.all()}

    # Previous period for trend
    prev_q = (
        select(
            FluCase.country_code,
            func.sum(FluCase.new_cases).label("total"),
        )
        .where(and_(FluCase.time >= prev_since, FluCase.time < since))
        .group_by(FluCase.country_code)
    )
    prev_result = await db.execute(prev_q)
    prev_map = {r.country_code: r.total for r in prev_result.all()}

    # Dominant flu type per country
    type_q = (
        select(
            FluCase.country_code,
            FluCase.flu_type,
            func.sum(FluCase.new_cases).label("type_total"),
        )
        .where(and_(FluCase.time >= since, FluCase.flu_type.isnot(None)))
        .group_by(FluCase.country_code, FluCase.flu_type)
    )
    type_result = await db.execute(type_q)
    dominant_types: dict[str, str] = {}
    type_max: dict[str, int] = {}
    for r in type_result.all():
        if r.country_code not in type_max or r.type_total > type_max[r.country_code]:
            type_max[r.country_code] = r.type_total
            dominant_types[r.country_code] = r.flu_type

    # Get all countries
    countries_result = await db.execute(select(Country))
    countries = countries_result.scalars().all()

    features = []
    for c in countries:
        cases = current_map.get(c.code, 0)
        prev = prev_map.get(c.code, 0)
        trend = round((cases - prev) / prev * 100, 1) if prev else 0.0
        per_100k = round(cases / c.population * 100_000, 2) if c.population else None

        features.append({
            "type": "Feature",
            "properties": {
                "country_code": c.code,
                "country_name": c.name,
                "new_cases_7d": cases,
                "cases_per_100k": per_100k,
                "trend_pct": trend,
                "dominant_flu_type": dominant_types.get(c.code),
                "severity_score": None,  # Filled by severity service
            },
            # Geometry is joined client-side with TopoJSON
            "id": c.code,
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
