"""Tests for genomics endpoints."""


def test_genomics_summary(seeded_client):
    resp = seeded_client.get("/api/genomics/summary?years=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sequences"] >= 5
    assert data["countries_tracked"] >= 3
    assert data["unique_clades"] >= 2


def test_genomics_trends(seeded_client):
    resp = seeded_client.get("/api/genomics/trends?country=US&years=10&top_n=4")
    assert resp.status_code == 200
    data = resp.json()
    assert data["country_code"] == "US"
    assert isinstance(data["top_clades"], list)
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
    for pt in data["data"]:
        assert "month" in pt
        assert "clade" in pt
        assert "sequences" in pt


def test_genomics_countries(seeded_client):
    resp = seeded_client.get("/api/genomics/countries?years=10&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["countries"]) >= 3
    assert all("country_code" in c for c in data["countries"])
