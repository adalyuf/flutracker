"""Tests for anomalies endpoint behavior."""

from datetime import datetime

from backend.app.models import Anomaly, Country, FluCase


def test_anomalies_only_increasing_alerts(seeded_client, session_factory):
    session = session_factory()
    try:
        session.add(Anomaly(
            detected_at=datetime.utcnow(),
            country_code="US",
            metric="weekly_cases",
            z_score=-3.1,
            description="Drop: -30% vs baseline (United States)",
            severity="high",
        ))
        session.add(Country(
            code="ZZ",
            name="Low Incidence Land",
            population=1_000_000,
            continent="Test",
        ))
        now = datetime.utcnow()
        for i in range(4):
            session.add(FluCase(
                time=now,
                country_code="ZZ",
                new_cases=1,  # 0.1 weekly cases per 100k (below threshold)
                source="test",
            ))
        session.add(Anomaly(
            detected_at=now,
            country_code="ZZ",
            metric="weekly_cases",
            z_score=4.2,
            description="Spike: +400% vs baseline (Low Incidence Land)",
            severity="critical",
        ))
        session.commit()
    finally:
        session.close()

    resp = seeded_client.get("/api/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    assert all(item["z_score"] > 0 for item in data)
    assert all(item["country_code"] != "ZZ" for item in data)
