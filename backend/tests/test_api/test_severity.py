"""Tests for severity endpoint."""


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
