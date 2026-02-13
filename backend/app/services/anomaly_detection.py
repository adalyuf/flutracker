from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import FluCase, Anomaly, Country

# Severity thresholds (z-score)
THRESHOLDS = {
    "low": 2.0,
    "medium": 2.5,
    "high": 3.0,
    "critical": 3.5,
}


def classify_severity(z_score: float) -> str:
    abs_z = abs(z_score)
    if abs_z >= THRESHOLDS["critical"]:
        return "critical"
    elif abs_z >= THRESHOLDS["high"]:
        return "high"
    elif abs_z >= THRESHOLDS["medium"]:
        return "medium"
    else:
        return "low"


async def detect_anomalies(db: AsyncSession) -> list[Anomaly]:
    """
    Detect anomalous flu case spikes using Z-score on rolling averages.
    Compares the most recent 4-week average against a 12-week baseline.
    """
    now = datetime.utcnow()
    recent_start = now - timedelta(weeks=4)
    baseline_start = now - timedelta(weeks=16)

    # Get all countries with data
    countries_result = await db.execute(select(Country))
    countries = countries_result.scalars().all()
    pop_map = {c.code: c.population for c in countries if c.population}

    new_anomalies = []

    for country in countries:
        # Weekly case totals for the last 16 weeks
        query = (
            select(
                func.date_trunc("week", FluCase.time).label("week"),
                func.sum(FluCase.new_cases).label("cases"),
            )
            .where(and_(
                FluCase.country_code == country.code,
                FluCase.time >= baseline_start,
            ))
            .group_by("week")
            .order_by("week")
        )
        result = await db.execute(query)
        rows = result.all()

        if len(rows) < 8:
            continue

        weekly_cases = [float(r.cases) for r in rows]

        # Baseline: first 12 weeks; recent: last 4 weeks
        baseline = weekly_cases[:-4] if len(weekly_cases) > 4 else weekly_cases[:len(weekly_cases)//2]
        recent = weekly_cases[-4:]

        if not baseline or not recent:
            continue

        baseline_mean = np.mean(baseline)
        baseline_std = np.std(baseline)

        if baseline_std < 1:
            continue

        recent_mean = np.mean(recent)
        z_score = (recent_mean - baseline_mean) / baseline_std

        if not country.population or country.population <= 0:
            continue
        recent_per_100k = (recent_mean / country.population) * 100_000

        if z_score >= THRESHOLDS["low"] and recent_per_100k > 1.0:
            pct_change = round((recent_mean - baseline_mean) / baseline_mean * 100, 1) if baseline_mean > 0 else 0.0

            anomaly = Anomaly(
                detected_at=now,
                country_code=country.code,
                metric="weekly_cases",
                z_score=round(z_score, 2),
                description=f"Spike: {pct_change:+.1f}% vs 12-week baseline ({country.name})",
                severity=classify_severity(z_score),
            )
            new_anomalies.append(anomaly)

    # Also check region-level anomalies for countries with regional data
    region_anomalies = await _detect_region_anomalies(db, now, baseline_start, recent_start, pop_map)
    new_anomalies.extend(region_anomalies)

    # Rebuild anomalies table from latest computation.
    await db.execute(delete(Anomaly))
    for anomaly in new_anomalies:
        db.add(anomaly)
    await db.commit()
    return new_anomalies


async def _detect_region_anomalies(
    db: AsyncSession,
    now: datetime,
    baseline_start: datetime,
    recent_start: datetime,
    pop_map: dict[str, int],
) -> list[Anomaly]:
    """Detect anomalies at the region level for countries with detailed data."""
    # Get distinct country+region combinations
    distinct_q = (
        select(FluCase.country_code, FluCase.region)
        .where(and_(FluCase.time >= baseline_start, FluCase.region.isnot(None)))
        .distinct()
    )
    result = await db.execute(distinct_q)
    pairs = result.all()

    anomalies = []
    for country_code, region in pairs:
        query = (
            select(
                func.date_trunc("week", FluCase.time).label("week"),
                func.sum(FluCase.new_cases).label("cases"),
            )
            .where(and_(
                FluCase.country_code == country_code,
                FluCase.region == region,
                FluCase.time >= baseline_start,
            ))
            .group_by("week")
            .order_by("week")
        )
        result = await db.execute(query)
        rows = result.all()

        if len(rows) < 8:
            continue

        weekly = [float(r.cases) for r in rows]
        baseline = weekly[:-4]
        recent = weekly[-4:]

        baseline_mean = np.mean(baseline)
        baseline_std = np.std(baseline)

        if baseline_std < 1:
            continue

        recent_mean = np.mean(recent)
        z_score = (recent_mean - baseline_mean) / baseline_std

        country_population = pop_map.get(country_code)
        if not country_population or country_population <= 0:
            continue
        recent_per_100k = (recent_mean / country_population) * 100_000

        # Only flag high severity for regions to avoid noise
        if z_score >= THRESHOLDS["high"] and recent_per_100k > 1.0:
            anomaly = Anomaly(
                detected_at=now,
                country_code=country_code,
                region=region,
                metric="weekly_cases",
                z_score=round(z_score, 2),
                description=f"Regional spike: {region} ({country_code})",
                severity=classify_severity(z_score),
            )
            anomalies.append(anomaly)

    return anomalies
