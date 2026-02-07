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
