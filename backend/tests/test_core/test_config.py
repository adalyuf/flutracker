"""Tests for config URL normalization."""

from backend.app.config import Settings


def test_railway_url_normalization():
    """Plain postgresql:// URL gets converted to postgresql+asyncpg://."""
    s = Settings(
        database_url="postgresql://user:pass@host:5432/db",
        _env_file=None,
    )
    assert s.database_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_asyncpg_url_unchanged():
    """Already-correct asyncpg URL is not modified."""
    url = "postgresql+asyncpg://user:pass@host:5432/db"
    s = Settings(database_url=url, _env_file=None)
    assert s.database_url == url


def test_sync_url_derived():
    """database_url_sync is set from the original Railway URL."""
    s = Settings(
        database_url="postgresql://user:pass@host:5432/db",
        _env_file=None,
    )
    assert s.database_url_sync == "postgresql://user:pass@host:5432/db"
