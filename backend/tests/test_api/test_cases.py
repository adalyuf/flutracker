"""Tests for cases endpoints."""


def test_get_cases(seeded_client):
    resp = seeded_client.get("/api/cases")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) > 0
    # Should be ordered by time descending
    times = [c["time"] for c in data]
    assert times == sorted(times, reverse=True)


def test_get_cases_filter_country(seeded_client):
    resp = seeded_client.get("/api/cases?country=GB")
    assert resp.status_code == 200
    data = resp.json()
    assert all(c["country_code"] == "GB" for c in data)


def test_get_cases_by_region(seeded_client):
    resp = seeded_client.get("/api/cases/by-region?country=US")
    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] == "US"
    region_names = {r["region"] for r in data["regions"]}
    assert {"California", "Texas", "Florida"} == region_names


def test_flu_types(seeded_client):
    resp = seeded_client.get("/api/flu-types?days=365")
    assert resp.status_code == 200
    data = resp.json()
    types = {b["flu_type"] for b in data["breakdown"]}
    assert {"H3N2", "H1N1"} == types
    # Percentages should sum to ~100
    total_pct = sum(b["percentage"] for b in data["breakdown"])
    assert 99.0 <= total_pct <= 101.0
