import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import AppSession, UserAccount
from app.models.enums import AccountStatus

SESSION_COOKIE = "health_avatar_session"
CSRF_COOKIE = "health_avatar_csrf"
DB = Annotated[Session, Depends(get_db)]
Configured = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Actor:
    user_id: Any
    is_system_administrator: bool = False


class AuthenticationError(ValueError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_google_token(token: str, audience: str) -> dict[str, Any]:
    """Validate signature, issuer, expiry, and audience with Google's maintained library."""
    try:
        claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            token, google_requests.Request(), audience
        )
    except ValueError as exc:
        raise AuthenticationError("Google identity token is invalid") from exc
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise AuthenticationError("Google identity token issuer is invalid")
    return dict(claims)


def provision_google_account(session: Session, claims: dict[str, Any]) -> UserAccount:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationError("Google identity token has no subject")
    account = session.scalar(
        select(UserAccount).where(
            UserAccount.auth_provider == "google", UserAccount.provider_subject == subject
        )
    )
    now = datetime.now(UTC)
    email = str(claims.get("email", ""))
    verified = claims.get("email_verified") is True
    if account is None:
        account = UserAccount(
            auth_provider="google",
            provider_subject=subject,
            email=email,
            email_verified=verified,
            display_name=str(claims.get("name") or "Google user"),
            profile_image_url=str(claims["picture"]) if claims.get("picture") else None,
            account_status=AccountStatus.PENDING,
            is_active=False,
        )
        session.add(account)
    else:
        account.email = email
        account.email_verified = verified
        account.display_name = str(claims.get("name") or account.display_name)
        account.profile_image_url = (
            str(claims["picture"]) if claims.get("picture") else account.profile_image_url
        )
    account.last_login_at = now
    session.commit()
    session.refresh(account)
    return account


def create_session(session: Session, account: UserAccount, settings: Settings) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session.add(
        AppSession(
            user_account_id=account.id,
            token_hash=_hash(token),
            csrf_token_hash=_hash(csrf),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
        )
    )
    session.commit()
    return token, csrf


def invalidate_session(session: Session, token: str | None) -> None:
    if not token:
        return
    app_session = session.scalar(select(AppSession).where(AppSession.token_hash == _hash(token)))
    if app_session is not None:
        app_session.invalidated_at = datetime.now(UTC)
        session.commit()


def resolve_account(session: Session, token: str | None) -> UserAccount | None:
    if not token:
        return None
    now = datetime.now(UTC)
    app_session = session.scalar(
        select(AppSession).where(
            AppSession.token_hash == _hash(token),
            AppSession.invalidated_at.is_(None),
            AppSession.expires_at > now,
        )
    )
    if app_session is None:
        return None
    return session.get(UserAccount, app_session.user_account_id)


def get_current_account(request: Request, session: DB) -> UserAccount:
    account = resolve_account(session, request.cookies.get(SESSION_COOKIE))
    if account is None:
        raise HTTPException(
            401, detail={"code": "authentication_required", "message": "Sign in required"}
        )
    if not account.is_active or account.account_status != AccountStatus.ACTIVE:
        raise HTTPException(
            403, detail={"code": "account_inactive", "message": "Account is pending or disabled"}
        )
    return account


def get_actor(account: Annotated[UserAccount, Depends(get_current_account)]) -> Actor:
    return Actor(account.id, account.is_system_administrator)


def require_csrf(
    request: Request,
    session: DB,
    settings: Configured,
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    token = request.cookies.get(SESSION_COOKIE)
    supplied = request.headers.get("X-CSRF-Token")
    cookie_value = request.cookies.get(CSRF_COOKIE)
    if (
        not token
        or not supplied
        or not cookie_value
        or not secrets.compare_digest(supplied, cookie_value)
    ):
        raise HTTPException(
            403, detail={"code": "csrf_failed", "message": "CSRF validation failed"}
        )
    app_session = session.scalar(select(AppSession).where(AppSession.token_hash == _hash(token)))
    if app_session is None or not secrets.compare_digest(
        app_session.csrf_token_hash, _hash(supplied)
    ):
        raise HTTPException(
            403, detail={"code": "csrf_failed", "message": "CSRF validation failed"}
        )


def cookie_options(settings: Settings) -> dict[str, Any]:
    return {"httponly": True, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
