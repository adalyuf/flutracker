"""Tests for forecasting service."""

from datetime import datetime, timedelta
import pytest
from backend.app.services.forecasting import generate_forecast


class TestForecasting:
    def test_generate_forecast_basic(self):
        """Test basic forecast generation with sufficient data."""
        now = datetime.utcnow()
        dates = [now - timedelta(weeks=12 - i) for i in range(12)]
        # Simulate a bell curve
        values = [100, 200, 400, 700, 1000, 1200, 1100, 800, 500, 300, 150, 100]

        points, peak_date, peak_mag = generate_forecast(dates, values, 4)

        assert len(points) == 4
        assert all(p.predicted_cases >= 0 for p in points)
        assert all(p.lower_80 <= p.predicted_cases <= p.upper_80 for p in points)
        assert all(p.lower_95 <= p.lower_80 for p in points)
        assert all(p.upper_95 >= p.upper_80 for p in points)

    def test_generate_forecast_insufficient_data(self):
        """Test forecast with too little data."""
        points, _, _ = generate_forecast([], [], 4)
        assert len(points) == 0

    def test_generate_forecast_flat_data(self):
        """Test forecast with constant values."""
        now = datetime.utcnow()
        dates = [now - timedelta(weeks=12 - i) for i in range(12)]
        values = [500] * 12

        points, _, _ = generate_forecast(dates, values, 4)
        assert len(points) == 4
        # With flat data, predictions should be near 500
        for p in points:
            assert 0 <= p.predicted_cases <= 2000

    def test_generate_forecast_increasing(self):
        """Test forecast with steadily increasing data."""
        now = datetime.utcnow()
        dates = [now - timedelta(weeks=12 - i) for i in range(12)]
        values = [i * 100 for i in range(1, 13)]

        points, _, _ = generate_forecast(dates, values, 4)
        assert len(points) == 4
