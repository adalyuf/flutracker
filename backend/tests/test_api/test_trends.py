"""Tests for trends endpoints and helper functions."""

from datetime import datetime

from backend.app.routers.trends import _season_label, _season_boundaries


# --- Unit tests for helper functions ---

def test_season_label():
    assert _season_label(2023) == "2023-24"
    assert _season_label(2019) == "2019-20"
    assert _season_label(1999) == "1999-00"


def test_season_boundaries_november():
    """November date → season starts Oct 1 of same year."""
    start, end = _season_boundaries(datetime(2024, 11, 15))
    assert start == datetime(2024, 10, 1)
    assert end.year == 2025 and end.month == 9


def test_season_boundaries_march():
    """March date → season starts Oct 1 of previous year."""
    start, end = _season_boundaries(datetime(2025, 3, 1))
    assert start == datetime(2024, 10, 1)
    assert end.year == 2025 and end.month == 9


# --- API endpoint tests ---

def test_get_trends(seeded_client):
    resp = seeded_client.get("/api/trends?country=US")
    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] == "US"
    assert data["granularity"] == "week"
    assert len(data["data"]) > 0
    for pt in data["data"]:
        assert "date" in pt
        assert "cases" in pt


def test_get_global_trends(seeded_client):
    resp = seeded_client.get("/api/trends/global")
    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] is None
    assert len(data["data"]) > 0


def test_compare_trends(seeded_client):
    resp = seeded_client.get("/api/trends/compare?countries=US,GB")
    assert resp.status_code == 200
    data = resp.json()
    assert "US" in data["series"]
    assert "GB" in data["series"]


def test_historical_seasons(seeded_client):
    resp = seeded_client.get("/api/trends/historical-seasons?country=US&seasons=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] == "US"
    assert "current_season" in data
    assert "past_seasons" in data
    assert len(data["past_seasons"]) <= 2
    for pt in data["current_season"]["data"]:
        datetime.strptime(pt["date"], "%Y-%m-%d")
