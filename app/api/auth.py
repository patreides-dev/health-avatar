# ruff: noqa: E501
import secrets
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import UserAccount
from app.models.enums import AccountStatus
from app.services.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    cookie_options,
    create_session,
    invalidate_session,
    provision_google_account,
    require_csrf,
    resolve_account,
    verify_google_token,
)

router = APIRouter(prefix="/auth", include_in_schema=False)
DB = Annotated[Session, Depends(get_db)]
Configured = Annotated[Settings, Depends(get_settings)]


@router.get("/login", response_class=HTMLResponse)
def login_page(settings: Configured) -> str:
    development = (
        "<p class='warning'>Development authentication is enabled. Unsafe for production.</p><form method='post' action='/auth/development-login'><label>Synthetic identity <select name='identity'><option value='owner'>Kevin Demo Owner</option><option value='viewer'>Andrea Demo Viewer</option><option value='pending'>Pending Demo User</option><option value='administrator'>Administrator Demo</option></select></label><button>Development sign in</button></form>"
        if settings.development_auth_enabled and not settings.is_production
        else ""
    )
    google = (
        "<a class='button' href='/auth/google'>Sign in with Google</a>"
        if settings.google_client_id
        else "<p>Google sign-in is not configured for this environment.</p>"
    )
    return f"<!doctype html><html><meta name='viewport' content='width=device-width'><title>Health Avatar sign in</title><style>body{{font:16px system-ui;max-width:42rem;margin:3rem auto;padding:1rem}}.warning{{color:#9b2c2c}}.button,button{{display:inline-block;padding:.8rem 1rem}}</style><main><h1>Health Avatar</h1><p>Private health information. Sign in only on a trusted device.</p>{google}{development}</main></html>"


@router.get("/google")
def google_login(settings: Configured) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(
            503,
            detail={"code": "google_not_configured", "message": "Google sign-in is not configured"},
        )
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    signed = URLSafeTimedSerializer(settings.session_secret, salt="oidc-state").dumps(
        {"state": state, "nonce": nonce}
    )
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
        }
    )
    response = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")
    response.set_cookie("health_avatar_oidc_state", signed, max_age=600, **cookie_options(settings))
    return response


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str,
    state: str,
    session: DB,
    settings: Configured,
) -> RedirectResponse:
    signed = request.cookies.get("health_avatar_oidc_state")
    try:
        expected = URLSafeTimedSerializer(settings.session_secret, salt="oidc-state").loads(
            signed or "", max_age=600
        )
    except BadSignature as exc:
        raise HTTPException(
            400, detail={"code": "invalid_oidc_state", "message": "Login state is invalid"}
        ) from exc
    if not isinstance(expected, dict) or not secrets.compare_digest(
        str(expected.get("state", "")), state
    ):
        raise HTTPException(
            400, detail={"code": "invalid_oidc_state", "message": "Login state is invalid"}
        )
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if token_response.status_code != 200 or "id_token" not in token_response.json():
        raise HTTPException(
            401, detail={"code": "google_login_failed", "message": "Google login failed"}
        )
    claims = verify_google_token(token_response.json()["id_token"], settings.google_client_id)
    if not secrets.compare_digest(str(claims.get("nonce", "")), str(expected.get("nonce", ""))):
        raise HTTPException(
            401,
            detail={"code": "invalid_oidc_nonce", "message": "Google login nonce is invalid"},
        )
    account = provision_google_account(session, claims)
    if account.account_status == AccountStatus.DISABLED:
        raise HTTPException(
            403, detail={"code": "account_disabled", "message": "Account is disabled"}
        )
    token, csrf = create_session(session, account, settings)
    response = RedirectResponse("/pending" if not account.is_active else "/app", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.session_hours * 3600, **cookie_options(settings)
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.session_hours * 3600,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.delete_cookie("health_avatar_oidc_state")
    return response


@router.post("/development-login")
def development_login(
    session: DB,
    settings: Configured,
    identity: str = Form(),
) -> RedirectResponse:
    if settings.is_production or not settings.development_auth_enabled:
        raise HTTPException(404, detail={"code": "not_found", "message": "Resource not found"})
    subjects = {
        "owner": "dev-owner",
        "viewer": "dev-viewer",
        "pending": "dev-pending",
        "administrator": "dev-admin",
    }
    subject = subjects.get(identity)
    if subject is None:
        raise HTTPException(
            400, detail={"code": "invalid_identity", "message": "Unknown synthetic identity"}
        )
    account = session.scalar(
        select(UserAccount).where(
            UserAccount.auth_provider == "development", UserAccount.provider_subject == subject
        )
    )
    if account is None:
        raise HTTPException(
            409, detail={"code": "seed_required", "message": "Run the development seed first"}
        )
    if account.account_status == AccountStatus.DISABLED:
        raise HTTPException(
            403, detail={"code": "account_disabled", "message": "Account is disabled"}
        )
    token, csrf = create_session(session, account, settings)
    response = RedirectResponse(
        "/pending" if account.account_status == AccountStatus.PENDING else "/app", status_code=303
    )
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.session_hours * 3600, **cookie_options(settings)
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.session_hours * 3600,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, session: DB) -> RedirectResponse:
    invalidate_session(session, request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return response


def browser_account(request: Request, session: DB) -> UserAccount | None:
    return resolve_account(session, request.cookies.get(SESSION_COOKIE))
