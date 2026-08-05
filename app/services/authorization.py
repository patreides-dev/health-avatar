from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AccessGrant, UserAccount
from app.models.enums import AccessRole
from app.services.auth import Actor


class AuthorizationError(PermissionError):
    pass


class Action(StrEnum):
    VIEW = "view"
    SUBMIT = "submit"
    APPROVE = "approve"
    CORRECT = "correct"
    MANAGE_ACCESS = "manage_access"


def active_grant(session: Session, actor: Actor, person_id: UUID) -> AccessGrant | None:
    now = datetime.now(UTC)
    account = session.get(UserAccount, actor.user_id)
    if account is None or not account.is_active:
        return None
    return session.scalar(
        select(AccessGrant)
        .where(
            AccessGrant.user_account_id == actor.user_id,
            AccessGrant.person_id == person_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
        )
        .order_by(AccessGrant.granted_at.desc(), AccessGrant.id)
    )


def authorize(session: Session, actor: Actor, person_id: UUID, action: Action) -> AccessGrant:
    grant = active_grant(session, actor, person_id)
    if grant is None:
        raise AuthorizationError("Resource not found")
    role = AccessRole(grant.role)
    allowed = action == Action.VIEW
    if action == Action.SUBMIT:
        allowed = role in {AccessRole.OWNER, AccessRole.CAREGIVER}
    elif action in {Action.APPROVE, Action.CORRECT}:
        allowed = role == AccessRole.OWNER or (role == AccessRole.CAREGIVER and grant.can_approve)
    elif action == Action.MANAGE_ACCESS:
        allowed = role == AccessRole.OWNER
    if not allowed:
        raise AuthorizationError("Operation is not permitted")
    return grant


def require_system_administrator(actor: Actor) -> None:
    if not actor.is_system_administrator:
        raise AuthorizationError("System administrator privileges required")
