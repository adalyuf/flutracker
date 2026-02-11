"""Simple in-memory TTL cache for API responses."""

import time
from typing import Any

from backend.app.config import get_settings

_store: dict[str, tuple[float, Any]] = {}


def get(key: str) -> Any | None:
    """Return cached value if still valid, else None."""
    entry = _store.get(key)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() > expires_at:
        del _store[key]
        return None
    return value


def put(key: str, value: Any, ttl: int | None = None) -> None:
    """Store a value with TTL (defaults to settings.cache_ttl seconds)."""
    if ttl is None:
        ttl = get_settings().cache_ttl
    _store[key] = (time.monotonic() + ttl, value)


def invalidate(prefix: str = "") -> None:
    """Remove all entries matching a key prefix (or all if empty)."""
    if not prefix:
        _store.clear()
    else:
        keys = [k for k in _store if k.startswith(prefix)]
        for k in keys:
            del _store[k]
