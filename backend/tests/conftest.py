"""Pytest configuration and shared fixtures."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import Country, FluCase, Anomaly


# No-op lifespan so TestClient doesn't try to connect to the real DB
@asynccontextmanager
async def _noop_lifespan(app):
    yield


app.router.lifespan_context = _noop_lifespan


# Use SQLite for tests (in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///file::memory:?cache=shared"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _register_sqlite_functions(dbapi_conn, connection_record):
    """Register PostgreSQL-compatible functions for SQLite."""
    from datetime import datetime as dt

    def date_trunc(part, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = dt.fromisoformat(value)
        if part == "day":
            return value.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        elif part == "week":
            # ISO week: Monday-based
            day_of_week = value.weekday()
            start = value - timedelta(days=day_of_week)
            return start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        elif part == "month":
            return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        return value.isoformat()

    dbapi_conn.create_function("date_trunc", 2, date_trunc)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

    from sqlalchemy import event as sa_event
    sa_event.listen(engine.sync_engine, "connect", _register_sqlite_functions)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    session_maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def seeded_db(db_session):
    """Database with sample test data."""
    # Add test countries
    countries = [
        Country(code="US", name="United States", population=340_000_000, continent="North America"),
        Country(code="GB", name="United Kingdom", population=68_000_000, continent="Europe"),
        Country(code="BR", name="Brazil", population=216_000_000, continent="South America"),
    ]
    for c in countries:
        db_session.add(c)

    # Add test cases
    now = datetime.utcnow()
    for i in range(12):
        week_start = now - timedelta(weeks=12 - i)
        for country, base in [("US", 5000), ("GB", 1000), ("BR", 3000)]:
            # Simulate a flu season curve
            multiplier = 1 + 0.5 * (6 - abs(i - 6)) / 6
            cases = int(base * multiplier)
            db_session.add(FluCase(
                time=week_start,
                country_code=country,
                new_cases=cases,
                flu_type="H3N2" if i % 3 == 0 else "H1N1",
                source="test",
            ))
            # Add some with region data
            if country == "US":
                for state, factor in [("California", 0.12), ("Texas", 0.09), ("Florida", 0.07)]:
                    db_session.add(FluCase(
                        time=week_start,
                        country_code="US",
                        region=state,
                        new_cases=int(cases * factor),
                        flu_type="H3N2" if i % 3 == 0 else "H1N1",
                        source="test",
                    ))

    # Add a test anomaly
    db_session.add(Anomaly(
        detected_at=now,
        country_code="US",
        metric="weekly_cases",
        z_score=3.2,
        description="Spike: +45% vs baseline (United States)",
        severity="high",
    ))

    await db_session.commit()
    yield db_session


@pytest.fixture
def client(db_session):
    """FastAPI test client with overridden database dependency."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(seeded_db):
    """FastAPI test client backed by a seeded database."""
    async def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory cache before each test."""
    from backend.app import cache
    cache.invalidate()
    yield
    cache.invalidate()
