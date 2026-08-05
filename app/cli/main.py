# ruff: noqa: B008,E501
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import typer
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import (
    AccessGrant,
    AuditEvent,
    CandidateRecord,
    Person,
    ProcessingRun,
    SourceArtifact,
    SourceSystem,
    UserAccount,
)
from app.services.auth import Actor
from app.services.authorization import (
    Action,
    AuthorizationError,
    authorize,
    require_system_administrator,
)
from app.services.catalog import seed_development
from app.services.ingestion import ingest_csv
from app.services.promotion import approve_candidate, reject_candidate
from app.services.storage import LocalArtifactStorage

cli = typer.Typer(help="Health Avatar trusted local administration CLI.")
db_cli, seed_cli, import_cli = typer.Typer(), typer.Typer(), typer.Typer()
users_cli, access_cli = typer.Typer(), typer.Typer()
artifacts_cli, processing_cli, candidates_cli = typer.Typer(), typer.Typer(), typer.Typer()
for group, name in (
    (db_cli, "db"),
    (seed_cli, "seed"),
    (import_cli, "import"),
    (users_cli, "users"),
    (access_cli, "access"),
    (artifacts_cli, "artifacts"),
    (processing_cli, "processing"),
    (candidates_cli, "candidates"),
):
    cli.add_typer(group, name=name)


def actor(session: Session, actor_user: UUID) -> Actor:
    account = session.get(UserAccount, actor_user)
    if account is None or not account.is_active:
        raise typer.BadParameter("Actor must be an active user account")
    return Actor(account.id, account.is_system_administrator)


def admin_actor(session: Session, actor_user: UUID) -> Actor:
    value = actor(session, actor_user)
    try:
        require_system_administrator(value)
    except AuthorizationError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return value


def audit(session: Session, value: Actor, action: str, target_type: str, target_id: UUID) -> None:
    session.add(
        AuditEvent(
            actor_user_account_id=value.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details_json={},
        )
    )


def authorized_run(session: Session, value: Actor, run_id: UUID) -> ProcessingRun:
    run = session.get(ProcessingRun, run_id)
    artifact = session.get(SourceArtifact, run.source_artifact_id) if run else None
    if run is None or artifact is None or artifact.subject_person_id is None:
        raise typer.BadParameter("Processing run not found")
    try:
        authorize(session, value, artifact.subject_person_id, Action.VIEW)
    except AuthorizationError as exc:
        raise typer.BadParameter("Processing run not found") from exc
    return run


@db_cli.command("upgrade")
def db_upgrade() -> None:
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@seed_cli.command("development")
def seed_development_command() -> None:
    with SessionLocal() as session:
        typer.echo(seed_development(session))


@import_cli.command("csv")
def import_csv_command(
    path: Path,
    person_external_reference: str = typer.Option(...),
    source_system: str = typer.Option(...),
    actor_user: UUID = typer.Option(...),
) -> None:
    if not path.is_file():
        raise typer.BadParameter("PATH must be a readable file")
    with SessionLocal() as session:
        person = session.scalar(
            select(Person).where(Person.external_reference == person_external_reference)
        )
        source = session.scalar(select(SourceSystem).where(SourceSystem.name == source_system))
        if person is None or source is None:
            raise typer.BadParameter("Unknown person or source system")
        settings = get_settings()
        _, run, batch = ingest_csv(
            session,
            content=path.read_bytes(),
            filename=path.name,
            source_system=source,
            subject_person=person,
            actor=actor(session, actor_user),
            storage=LocalArtifactStorage(settings.artifact_storage_path),
            settings=settings,
        )
        typer.echo(
            f"batch={batch.id} run={run.id} status={batch.status} accepted={batch.accepted_rows} rejected={batch.rejected_rows}"
        )


@users_cli.command("list")
def users_list(actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        admin_actor(session, actor_user)
        for user in session.scalars(
            select(UserAccount).order_by(UserAccount.created_at, UserAccount.id)
        ):
            typer.echo(f"{user.id} {user.account_status} {user.display_name}")


def set_user_status(user_id: UUID, actor_user: UUID, enabled: bool) -> None:
    with SessionLocal() as session:
        value = admin_actor(session, actor_user)
        user = session.get(UserAccount, user_id)
        if user is None or (not enabled and user.id == value.user_id):
            raise typer.BadParameter("User not found or unsafe change")
        user.account_status, user.is_active = ("active", True) if enabled else ("disabled", False)
        audit(
            session, value, "user.activate" if enabled else "user.disable", "user_account", user.id
        )
        session.commit()


@users_cli.command("activate")
def users_activate(user_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    set_user_status(user_id, actor_user, True)


@users_cli.command("disable")
def users_disable(user_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    set_user_status(user_id, actor_user, False)


@access_cli.command("grant")
def access_grant(
    user: UUID = typer.Option(...),
    person: UUID = typer.Option(...),
    role: str = typer.Option(...),
    actor_user: UUID = typer.Option(...),
    can_approve: bool = False,
) -> None:
    with SessionLocal() as session:
        value = admin_actor(session, actor_user)
        if (
            session.get(UserAccount, user) is None
            or session.get(Person, person) is None
            or role not in {"owner", "administrator", "caregiver", "viewer"}
        ):
            raise typer.BadParameter("Invalid grant")
        grant = AccessGrant(
            user_account_id=user,
            person_id=person,
            role=role,
            can_approve=can_approve,
            granted_by_user_account_id=value.user_id,
        )
        session.add(grant)
        session.flush()
        audit(session, value, "access.grant", "access_grant", grant.id)
        session.commit()
        typer.echo(grant.id)


@access_cli.command("revoke")
def access_revoke(grant_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        value = admin_actor(session, actor_user)
        grant = session.get(AccessGrant, grant_id)
        if grant is None:
            raise typer.BadParameter("Grant not found")
        grant.revoked_at, grant.revoked_by_user_account_id = datetime.now(UTC), value.user_id
        audit(session, value, "access.revoke", "access_grant", grant.id)
        session.commit()


@artifacts_cli.command("list")
def artifacts_list(actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        value = actor(session, actor_user)
        person_ids = select(AccessGrant.person_id).where(
            AccessGrant.user_account_id == value.user_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > datetime.now(UTC)),
        )
        for item in session.scalars(
            select(SourceArtifact)
            .where(SourceArtifact.subject_person_id.in_(person_ids))
            .order_by(SourceArtifact.received_at.desc(), SourceArtifact.id)
        ):
            typer.echo(f"{item.id} {item.artifact_kind} {item.processing_status}")


@processing_cli.command("show")
def processing_show(run_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        run = authorized_run(session, actor(session, actor_user), run_id)
        typer.echo(f"{run.id} {run.status} candidates={run.candidate_count}")


@candidates_cli.command("list")
def candidates_list(run_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        authorized_run(session, actor(session, actor_user), run_id)
        for item in session.scalars(
            select(CandidateRecord)
            .where(CandidateRecord.processing_run_id == run_id)
            .order_by(CandidateRecord.created_at, CandidateRecord.id)
        ):
            typer.echo(f"{item.id} {item.source_locator} {item.status}")


@candidates_cli.command("approve")
def candidates_approve(candidate_id: UUID, actor_user: UUID = typer.Option(...)) -> None:
    with SessionLocal() as session:
        candidate = session.get(CandidateRecord, candidate_id)
        if candidate is None:
            raise typer.BadParameter("Candidate not found")
        observation = approve_candidate(
            session, candidate=candidate, actor=actor(session, actor_user)
        )
        typer.echo(observation.id)


@candidates_cli.command("reject")
def candidates_reject(
    candidate_id: UUID, actor_user: UUID = typer.Option(...), reason: str = typer.Option(...)
) -> None:
    with SessionLocal() as session:
        candidate = session.get(CandidateRecord, candidate_id)
        if candidate is None:
            raise typer.BadParameter("Candidate not found")
        reject_candidate(
            session, candidate=candidate, actor=actor(session, actor_user), reason=reason
        )


@cli.command("validate")
def validate() -> None:
    get_settings()
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    typer.echo("Configuration and database connection are valid.")


if __name__ == "__main__":
    cli()
