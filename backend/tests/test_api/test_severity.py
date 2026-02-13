"""Tests for severity endpoint."""

from datetime import datetime, timedelta

from backend.app.models import FluCase


def test_severity_returns_list(seeded_client):
    resp = seeded_client.get("/api/severity")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_severity_skips_no_population(seeded_client):
    """All returned countries must have population (used in score calc)."""
    resp = seeded_client.get("/api/severity")
    data = resp.json()
    # The seeded countries all have population, so they should all appear
    codes = {d["country_code"] for d in data}
    assert "US" in codes


def test_severity_score_components(seeded_client):
    resp = seeded_client.get("/api/severity")
    data = resp.json()
    for entry in data:
        assert 0 <= entry["score"] <= 100
        assert "rate_per_100k" in entry["components"]
        assert "rate_score" in entry["components"]
        assert "growth_pct" in entry["components"]
        assert "growth_score" in entry["components"]
        assert "dominant_type" in entry["components"]
        assert entry["level"] in ("low", "moderate", "high", "very_high", "critical")


def test_severity_ordering(seeded_client):
    resp = seeded_client.get("/api/severity")
    data = resp.json()
    scores = [d["score"] for d in data]
    assert scores == sorted(scores, reverse=True)


def test_severity_uses_country_metadata_fallback(session_factory, client):
    """Unseeded countries with data should still score when metadata provides population."""
    session = session_factory()
    now = datetime.utcnow()
    try:
        session.add(FluCase(
            time=now - timedelta(days=3),
            country_code="FI",
            new_cases=120,
            flu_type="H1N1",
            source="test",
        ))
        session.add(FluCase(
            time=now - timedelta(days=10),
            country_code="FI",
            new_cases=80,
            flu_type="H1N1",
            source="test",
        ))
        session.commit()
    finally:
        session.close()

    resp = client.get("/api/severity")
    assert resp.status_code == 200
    data = resp.json()
    fi = next((row for row in data if row["country_code"] == "FI"), None)
    assert fi is not None
    assert fi["country_name"] == "Finland"
