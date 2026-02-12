"""Tests for the in-memory TTL cache."""

from unittest.mock import patch

from backend.app import cache


def test_put_and_get():
    cache.put("k1", {"data": 42}, ttl=60)
    assert cache.get("k1") == {"data": 42}


def test_get_missing_key():
    assert cache.get("nonexistent") is None


def test_ttl_expiry():
    with patch("backend.app.cache.time") as mock_time:
        mock_time.monotonic.return_value = 1000.0
        cache.put("expiring", "value", ttl=10)

        # Still valid at t+9
        mock_time.monotonic.return_value = 1009.0
        assert cache.get("expiring") == "value"

        # Expired at t+11
        mock_time.monotonic.return_value = 1011.0
        assert cache.get("expiring") is None


def test_invalidate_all():
    cache.put("a", 1, ttl=60)
    cache.put("b", 2, ttl=60)
    cache.invalidate()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_invalidate_prefix():
    cache.put("countries:all", [1], ttl=60)
    cache.put("countries:EU", [2], ttl=60)
    cache.put("summary", {}, ttl=60)
    cache.invalidate("countries")
    assert cache.get("countries:all") is None
    assert cache.get("countries:EU") is None
    assert cache.get("summary") == {}


def test_default_ttl_from_settings():
    """put() without explicit TTL uses settings.cache_ttl (900s)."""
    with patch("backend.app.cache.time") as mock_time, patch("backend.app.cache.get_settings") as mock_settings:
        mock_settings.return_value.cache_ttl = 900
        mock_time.monotonic.return_value = 0.0
        cache.put("default_ttl", "val")

        # Should still be alive at 899s
        mock_time.monotonic.return_value = 899.0
        assert cache.get("default_ttl") == "val"

        # Should be expired at 901s
        mock_time.monotonic.return_value = 901.0
        assert cache.get("default_ttl") is None
