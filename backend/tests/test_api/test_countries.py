"""Tests for countries and summary endpoints."""


def test_list_countries(seeded_client):
    resp = seeded_client.get("/api/countries")
    assert resp.status_code == 200
    data = resp.json()
    codes = {c["code"] for c in data}
    assert {"US", "GB", "BR"} == codes
    # Each country should have case totals
    for c in data:
        assert "total_recent_cases" in c


def test_list_countries_filter_continent(seeded_client):
    resp = seeded_client.get("/api/countries?continent=Europe")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["code"] == "GB"


def test_countries_with_regions(seeded_client):
    resp = seeded_client.get("/api/countries/with-regions")
    assert resp.status_code == 200
    data = resp.json()
    assert "US" in data


def test_summary(seeded_client):
    resp = seeded_client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_countries_tracked"] == 3
    assert data["total_cases_7d"] >= 0
    assert data["total_cases_28d"] >= data["total_cases_7d"]
    assert "global_trend_pct" in data
    assert "last_updated" in data


def test_summary_has_top_countries(seeded_client):
    resp = seeded_client.get("/api/summary")
    data = resp.json()
    top = data["top_countries"]
    assert isinstance(top, list)
    assert len(top) <= 5
    # Top countries should be ordered by cases descending
    if len(top) >= 2:
        assert top[0]["total_recent_cases"] >= top[1]["total_recent_cases"]
