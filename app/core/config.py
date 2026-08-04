from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="HEALTH_AVATAR_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = (
        "postgresql+psycopg://health_avatar:development-only@localhost:5432/health_avatar"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
