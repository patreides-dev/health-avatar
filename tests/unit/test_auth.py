from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import AppSession, UserAccount
from app.services.auth import (
    AuthenticationError,
    create_session,
    provision_google_account,
    verify_google_token,
)


def claims(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "sub": "google-123",
        "email": "first@example.invalid",
        "email_verified": True,
        "name": "Synthetic Google User",
        "iss": "https://accounts.google.com",
    }
    value.update(changes)
    return value


def test_provider_subject_survives_email_change(session: Session) -> None:
    first = provision_google_account(session, claims())
    second = provision_google_account(session, claims(email="changed@example.invalid"))
    assert first.id == second.id
    assert second.email == "changed@example.invalid"
    assert session.scalar(select(func.count()).select_from(UserAccount)) == 1
    assert second.account_status == "pending" and not second.is_active


def test_unverified_email_is_recorded_as_untrusted(session: Session) -> None:
    account = provision_google_account(session, claims(email_verified=False))
    assert account.email and account.email_verified is False


@pytest.mark.parametrize("failure", ["wrong audience", "expired"])
def test_google_verifier_rejects_wrong_audience_and_expiry(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise ValueError(failure)

    monkeypatch.setattr("app.services.auth.id_token.verify_oauth2_token", fail)
    with pytest.raises(AuthenticationError, match="invalid"):
        verify_google_token("forged", "expected-audience")


def test_google_verifier_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.auth.id_token.verify_oauth2_token", lambda *_args: {"iss": "attacker"}
    )
    with pytest.raises(AuthenticationError, match="issuer"):
        verify_google_token("signed", "audience")


def test_production_configuration_rejects_unsafe_settings() -> None:
    with pytest.raises(ValidationError, match="DEVELOPMENT_AUTH_ENABLED"):
        Settings(app_env="production", development_auth_enabled=True)
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(
            app_env="production",
            development_auth_enabled=False,
            google_client_id="client",
            cookie_secure=True,
        )


def test_development_auth_unavailable_when_disabled(client: TestClient) -> None:
    original = client.app.dependency_overrides[get_settings]
    client.app.dependency_overrides[get_settings] = lambda: Settings(
        app_env="testing", development_auth_enabled=False
    )
    try:
        response = client.post("/auth/development-login", data={"identity": "owner"})
        assert response.status_code == 404
    finally:
        client.app.dependency_overrides[get_settings] = original


def test_logout_invalidates_server_session(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    headers = login("dev-owner")
    assert client.get("/api/v1/persons").status_code == 200
    response = client.post("/auth/logout", headers=headers, follow_redirects=False)
    assert response.status_code == 303
    app_session = seeded_session.scalar(select(AppSession).order_by(AppSession.created_at.desc()))
    assert app_session is not None and app_session.invalidated_at is not None
    assert client.get("/api/v1/persons").status_code == 401


def test_expired_session_is_rejected(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    login("dev-owner")
    app_session = seeded_session.scalar(select(AppSession).order_by(AppSession.created_at.desc()))
    assert app_session is not None
    app_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    seeded_session.commit()
    assert client.get("/api/v1/persons").status_code == 401


def test_disabled_account_is_rejected_immediately(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    login("dev-owner")
    account = seeded_session.scalar(
        select(UserAccount).where(UserAccount.provider_subject == "dev-owner")
    )
    assert account is not None
    account.is_active = False
    account.account_status = "disabled"
    seeded_session.commit()
    assert client.get("/api/v1/persons").status_code == 403
    with pytest.raises(AuthenticationError, match="cannot start"):
        create_session(
            seeded_session,
            account,
            Settings(app_env="testing", session_secret="synthetic-test-secret-not-for-production"),
        )


def test_disabled_account_cannot_use_development_login(
    client: TestClient, seeded_session: Session
) -> None:
    account = seeded_session.scalar(
        select(UserAccount).where(UserAccount.provider_subject == "dev-owner")
    )
    assert account is not None
    account.account_status = "disabled"
    account.is_active = False
    seeded_session.commit()
    response = client.post("/auth/development-login", data={"identity": "owner"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"
