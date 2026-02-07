from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import FluCase, Country
from backend.app.schemas import ForecastOut
from backend.app.services.forecasting import generate_forecast

router = APIRouter(tags=["forecast"])


@router.get("/forecast", response_model=ForecastOut)
async def get_forecast(
    country: str,
    weeks_ahead: int = Query(4, le=8),
    db: AsyncSession = Depends(get_db),
):
    country = country.upper()
    since = datetime.utcnow() - timedelta(weeks=52)

    # Get weekly case data for the past year
    query = (
        select(
            func.date_trunc("week", FluCase.time).label("bucket"),
            func.sum(FluCase.new_cases).label("cases"),
        )
        .where(and_(FluCase.country_code == country, FluCase.time >= since))
        .group_by("bucket")
        .order_by("bucket")
    )
    result = await db.execute(query)
    rows = result.all()

    dates = [r.bucket for r in rows]
    values = [r.cases for r in rows]

    forecast_data, peak_date, peak_magnitude = generate_forecast(
        dates, values, weeks_ahead
    )

    return ForecastOut(
        country_code=country,
        forecast_weeks=weeks_ahead,
        data=forecast_data,
        peak_date=peak_date,
        peak_magnitude=peak_magnitude,
    )
