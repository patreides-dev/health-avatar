from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="HEALTH_AVATAR_", env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://health_avatar:development-only@localhost:5432/health_avatar"
    )
    session_secret: str = "development-only-change-me"
    session_hours: int = 12
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    cookie_secure: bool = False
    development_auth_enabled: bool = False
    artifact_storage_path: Path = Path(".local/artifacts")
    max_artifact_bytes: int = 10 * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.is_production:
            if self.development_auth_enabled:
                raise ValueError("DEVELOPMENT_AUTH_ENABLED is forbidden in production")
            if len(self.session_secret) < 32 or self.session_secret == "development-only-change-me":
                raise ValueError("Production requires a strong SESSION_SECRET")
            if not self.cookie_secure:
                raise ValueError("Production requires COOKIE_SECURE=true")
            if not self.google_client_id:
                raise ValueError("Production requires GOOGLE_CLIENT_ID")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
