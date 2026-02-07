from pydantic_settings import BaseSettings
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
