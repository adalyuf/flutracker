from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import Anomaly, FluCase, Country
from backend.app.schemas import AnomalyOut

router = APIRouter(tags=["anomalies"])


@router.get("/anomalies", response_model=list[AnomalyOut])
async def get_anomalies(
    country: str | None = None,
    severity: str | None = None,
    days: int = Query(7, le=30),
    db: AsyncSession = Depends(get_db),
):
    anchor = (await db.execute(select(func.max(Anomaly.detected_at)))).scalar() or datetime.utcnow()
    case_anchor = (await db.execute(select(func.max(FluCase.time)))).scalar() or anchor
    case_since = case_anchor - timedelta(weeks=4)

    eligible_countries = (
        select(FluCase.country_code)
        .join(Country, Country.code == FluCase.country_code)
        .where(and_(
            FluCase.time >= case_since,
            Country.population.isnot(None),
            Country.population > 0,
        ))
        .group_by(FluCase.country_code, Country.population)
        .having(((func.sum(FluCase.new_cases) / 4.0) * 100000.0 / Country.population) > 1.0)
    )

    since = anchor - timedelta(days=days)
    query = (
        select(Anomaly)
        .where(and_(
            Anomaly.detected_at >= since,
            Anomaly.z_score > 0,
            Anomaly.country_code.in_(eligible_countries),
        ))
        .order_by(Anomaly.z_score.desc())
    )
    if country:
        query = query.where(Anomaly.country_code == country.upper())
    if severity:
        query = query.where(Anomaly.severity == severity)
    result = await db.execute(query)
    return result.scalars().all()
