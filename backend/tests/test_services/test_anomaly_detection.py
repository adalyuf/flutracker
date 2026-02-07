"""Tests for anomaly detection service."""

import pytest
from backend.app.services.anomaly_detection import classify_severity


class TestClassifySeverity:
    def test_low_severity(self):
        assert classify_severity(2.1) == "low"
        assert classify_severity(-2.1) == "low"

    def test_medium_severity(self):
        assert classify_severity(2.6) == "medium"

    def test_high_severity(self):
        assert classify_severity(3.1) == "high"

    def test_critical_severity(self):
        assert classify_severity(3.5) == "critical"
        assert classify_severity(5.0) == "critical"
        assert classify_severity(-4.0) == "critical"
