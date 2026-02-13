"""Tests for WHO FluNet scraper parsing logic."""

import pytest
from backend.ingestion.scrapers.who_flunet import WHOFluNetScraper


class TestWHOFluNetParser:
    def setup_method(self):
        self.scraper = WHOFluNetScraper()

    def test_parse_entry_with_subtypes(self):
        entry = {
            "ISO2": "US",
            "ISO_YEAR": 2026,
            "ISO_WEEK": 4,
            "AH1N12009": 150,
            "AH3": 200,
            "BYAM": 0,
            "BVIC": 50,
            "INF_A": 0,
            "INF_B": 0,
            "SPEC_PROCESSED_NB": 5000,
        }
        records = self.scraper._parse_entry(entry)
        assert len(records) == 3
        assert records[0].flu_type == "H1N1"
        assert records[0].new_cases == 150
        assert records[1].flu_type == "H3N2"
        assert records[1].new_cases == 200
        assert records[2].flu_type == "B/Victoria"

    def test_parse_entry_no_subtypes(self):
        entry = {
            "ISO2": "NG",
            "ISO_YEAR": 2026,
            "ISO_WEEK": 4,
            "ALL_INF": 30,
        }
        records = self.scraper._parse_entry(entry)
        assert len(records) == 1
        assert records[0].flu_type == "unknown"
        assert records[0].new_cases == 30

    def test_parse_entry_empty(self):
        entry = {
            "ISO2": "XX",
            "ISO_YEAR": 2026,
            "ISO_WEEK": 4,
        }
        records = self.scraper._parse_entry(entry)
        assert len(records) == 0

    def test_parse_entry_missing_country(self):
        entry = {"ISO_YEAR": 2026, "ISO_WEEK": 4}
        records = self.scraper._parse_entry(entry)
        assert len(records) == 0

    def test_parse_entry_invalid_week(self):
        entry = {"ISO2": "US", "ISO_YEAR": 2026, "ISO_WEEK": None}
        records = self.scraper._parse_entry(entry)
        assert len(records) == 0

    def test_parse_entry_maps_uk_constituents_to_gb(self):
        entry = {
            "ISO2": "XS",
            "ISO_YEAR": 2026,
            "ISO_WEEK": 4,
            "AH3": 120,
        }
        records = self.scraper._parse_entry(entry)
        assert len(records) == 1
        assert records[0].country_code == "GB"
        assert records[0].new_cases == 120


@pytest.mark.asyncio
async def test_fetch_range_aggregates_uk_components(monkeypatch):
    scraper = WHOFluNetScraper()

    payload = {
        "value": [
            {"ISO2": "XE", "ISO_YEAR": 2026, "ISO_WEEK": 4, "AH3": 100},
            {"ISO2": "XI", "ISO_YEAR": 2026, "ISO_WEEK": 4, "AH3": 50},
            {"ISO2": "XS", "ISO_YEAR": 2026, "ISO_WEEK": 4, "AH3": 25},
            {"ISO2": "XW", "ISO_YEAR": 2026, "ISO_WEEK": 4, "AH3": 25},
        ]
    }

    class _DummyResponse:
        def json(self):
            return payload

    async def _fake_get(url, **kwargs):
        return _DummyResponse()

    monkeypatch.setattr(scraper, "_get", _fake_get)
    records = await scraper.fetch_range(2026, 4, 2026, 4)
    await scraper.close()

    assert len(records) == 1
    assert records[0].country_code == "GB"
    assert records[0].flu_type == "H3N2"
    assert records[0].new_cases == 200
