"""Pytest configuration and shared fixtures."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import pytest
import asyncio
import httpx
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import Anomaly, Country, FluCase, GenomicSequence


# No-op lifespan so TestClient doesn't try to connect to the real DB
@asynccontextmanager
async def _noop_lifespan(app):
    yield


app.router.lifespan_context = _noop_lifespan


class AsyncSessionAdapter:
    """Tiny async facade over a sync SQLAlchemy session for tests."""

    def __init__(self, session: Session):
        self._session = session

    async def execute(self, *args: Any, **kwargs: Any):
        return self._session.execute(*args, **kwargs)

    async def commit(self) -> None:
        self._session.commit()

    async def flush(self) -> None:
        self._session.flush()

    async def rollback(self) -> None:
        self._session.rollback()

    async def close(self) -> None:
        self._session.close()

    async def refresh(self, instance: Any) -> None:
        self._session.refresh(instance)

    def add(self, instance: Any) -> None:
        self._session.add(instance)


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
        if part == "week":
            day_of_week = value.weekday()
            start = value - timedelta(days=day_of_week)
            return start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        if part == "month":
            return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        return value.isoformat()

    dbapi_conn.create_function("date_trunc", 2, date_trunc)


@pytest.fixture(scope="function")
def db_engine(tmp_path):
    test_db = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{test_db}")
    sa_event.listen(engine, "connect", _register_sqlite_functions)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture(scope="function")
def db_session(session_factory):
    session = session_factory()
    adapted = AsyncSessionAdapter(session)
    try:
        yield adapted
    finally:
        session.close()


@pytest.fixture(scope="function")
def seeded_db(session_factory):
    """Database with sample test data."""
    session = session_factory()
    try:
        # Add test countries
        countries = [
            Country(code="US", name="United States", population=340_000_000, continent="North America"),
            Country(code="GB", name="United Kingdom", population=68_000_000, continent="Europe"),
            Country(code="BR", name="Brazil", population=216_000_000, continent="South America"),
        ]
        for c in countries:
            session.add(c)

        # Add test cases
        now = datetime.utcnow()
        for i in range(12):
            week_start = now - timedelta(weeks=12 - i)
            for country, base in [("US", 5000), ("GB", 1000), ("BR", 3000)]:
                multiplier = 1 + 0.5 * (6 - abs(i - 6)) / 6
                cases = int(base * multiplier)
                session.add(FluCase(
                    time=week_start,
                    country_code=country,
                    new_cases=cases,
                    flu_type="H3N2" if i % 3 == 0 else "H1N1",
                    source="test",
                ))
                if country == "US":
                    for state, factor in [("California", 0.12), ("Texas", 0.09), ("Florida", 0.07)]:
                        session.add(FluCase(
                            time=week_start,
                            country_code="US",
                            region=state,
                            new_cases=int(cases * factor),
                            flu_type="H3N2" if i % 3 == 0 else "H1N1",
                            source="test",
                        ))

        # Add a test anomaly
        session.add(Anomaly(
            detected_at=now,
            country_code="US",
            metric="weekly_cases",
            z_score=3.2,
            description="Spike: +45% vs baseline (United States)",
            severity="high",
        ))

        # Add genomic sequence metadata samples
        genomic_rows = [
            ("US", "United States", "h3n2", "3C.2a1b.2a.2", "USA/CA-001/2024", now - timedelta(days=30)),
            ("US", "United States", "h3n2", "3C.2a1b.2a.2", "USA/TX-001/2024", now - timedelta(days=45)),
            ("GB", "United Kingdom", "h1n1pdm", "6B.1A.5a.2", "GBR/LON-001/2024", now - timedelta(days=40)),
            ("BR", "Brazil", "h3n2", "3C.2a1b.2a.2", "BRA/SP-001/2024", now - timedelta(days=50)),
            ("BR", "Brazil", "vic", "V1A.3a.2", "BRA/RJ-001/2023", now - timedelta(days=320)),
        ]
        for code, name, lineage, clade, strain, sample_date in genomic_rows:
            session.add(GenomicSequence(
                sample_date=sample_date,
                country_code=code,
                country_name=name,
                lineage=lineage,
                clade=clade,
                strain_name=strain,
                source="test",
                source_dataset="test_dataset",
            ))

        session.commit()
        yield
    finally:
        session.close()


def _override_get_db_with_factory(session_factory):
    async def override_get_db():
        session = session_factory()
        adapted = AsyncSessionAdapter(session)
        try:
            yield adapted
            await adapted.commit()
        except Exception:
            await adapted.rollback()
            raise
        finally:
            await adapted.close()

    return override_get_db


@pytest.fixture
def client(session_factory):
    """FastAPI test client with overridden database dependency."""
    app.dependency_overrides[get_db] = _override_get_db_with_factory(session_factory)

    class SyncASGIClient:
        def get(self, path: str):
            async def _request():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                    return await c.get(path)

            return asyncio.run(_request())

    try:
        yield SyncASGIClient()
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(session_factory, seeded_db):
    """FastAPI test client backed by a seeded database."""
    app.dependency_overrides[get_db] = _override_get_db_with_factory(session_factory)

    class SyncASGIClient:
        def get(self, path: str):
            async def _request():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
                    return await c.get(path)

            return asyncio.run(_request())

    try:
        yield SyncASGIClient()
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the in-memory cache before each test."""
    from backend.app import cache

    cache.invalidate()
    yield
    cache.invalidate()
