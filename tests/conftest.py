from collections.abc import Callable, Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import UserAccount
from app.services.auth import CSRF_COOKIE, SESSION_COOKIE, create_session
from app.services.catalog import seed_development


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db
    Base.metadata.drop_all(engine)


@pytest.fixture
def seeded_session(session: Session) -> Session:
    seed_development(session)
    return session


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="testing",
        database_url="sqlite+pysqlite:///:memory:",
        session_secret="synthetic-test-secret-not-for-production",
        development_auth_enabled=True,
        artifact_storage_path=tmp_path / "artifacts",
        max_artifact_bytes=2048,
    )


@pytest.fixture
def client(seeded_session: Session, test_settings: Settings) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        yield seeded_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def login(
    client: TestClient, seeded_session: Session, test_settings: Settings
) -> Callable[[str], dict[str, str]]:
    def do_login(subject: str) -> dict[str, str]:
        account = seeded_session.scalar(
            select(UserAccount).where(UserAccount.provider_subject == subject)
        )
        assert account is not None
        token, csrf = create_session(seeded_session, account, test_settings)
        client.cookies.set(SESSION_COOKIE, token)
        client.cookies.set(CSRF_COOKIE, csrf)
        return {"X-CSRF-Token": csrf}

    return do_login
