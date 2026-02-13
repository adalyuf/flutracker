from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://flutracker:changeme@localhost:5432/flutracker"
    database_url_sync: str = "postgresql://flutracker:changeme@localhost:5432/flutracker"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "info"
    scrape_enabled: bool = True
    scrape_interval_hours: int = 6
    cache_ttl: int = 900
    db_startup_max_attempts: int = 8
    db_startup_initial_backoff_seconds: int = 2
    db_startup_max_backoff_seconds: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def _normalize_db_urls(self):
        """Auto-convert DATABASE_URL for Railway/Heroku compatibility.

        Railway provides DATABASE_URL as postgresql://... — we derive
        the asyncpg and sync variants automatically so you only need to
        set one env var.
        """
        url = self.database_url
        # If the URL uses the plain 'postgresql://' driver (Railway/Heroku style),
        # derive both async and sync URLs from it.
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            self.database_url_sync = url
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
