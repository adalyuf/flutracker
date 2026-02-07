from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import Anomaly
from backend.app.schemas import AnomalyOut

router = APIRouter(tags=["anomalies"])


@router.get("/anomalies", response_model=list[AnomalyOut])
async def get_anomalies(
    country: str | None = None,
    severity: str | None = None,
    days: int = Query(7, le=30),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(days=days)
    query = (
        select(Anomaly)
        .where(Anomaly.detected_at >= since)
        .order_by(Anomaly.z_score.desc())
    )
    if country:
        query = query.where(Anomaly.country_code == country.upper())
    if severity:
        query = query.where(Anomaly.severity == severity)
    result = await db.execute(query)
    return result.scalars().all()
