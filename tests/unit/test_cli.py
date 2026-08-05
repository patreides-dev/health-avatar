# ruff: noqa: E501
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli import main as cli
from app.core.config import Settings
from app.models import AccessGrant, CandidateRecord, Person, ProcessingRun, UserAccount


def identity(session: Session, subject: str) -> UserAccount:
    account = session.scalar(select(UserAccount).where(UserAccount.provider_subject == subject))
    assert account is not None
    return account


@pytest.fixture
def cli_session(
    monkeypatch: pytest.MonkeyPatch, seeded_session: Session, tmp_path: Path
) -> Session:
    monkeypatch.setattr(cli, "SessionLocal", lambda: seeded_session)
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(app_env="testing", artifact_storage_path=tmp_path / "artifacts"),
    )
    return seeded_session


def test_database_seed_validate_and_user_commands(
    cli_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(cli.subprocess, "run", lambda command, check: called.append(command))
    cli.db_upgrade()
    assert called == [["alembic", "upgrade", "head"]]
    cli.seed_development_command()
    cli.validate()
    admin = identity(cli_session, "dev-admin")
    pending = identity(cli_session, "dev-pending")
    cli.users_list(actor_user=admin.id)
    cli.users_activate(pending.id, actor_user=admin.id)
    pending = cli_session.get(UserAccount, pending.id)
    assert pending is not None
    assert pending.is_active
    cli.users_disable(pending.id, actor_user=admin.id)
    pending = cli_session.get(UserAccount, pending.id)
    assert pending is not None
    assert not pending.is_active
    with pytest.raises(typer.BadParameter):
        cli.users_disable(admin.id, actor_user=admin.id)


def test_access_commands_create_audited_revocable_grant(cli_session: Session) -> None:
    admin = identity(cli_session, "dev-admin")
    pending = identity(cli_session, "dev-pending")
    person = cli_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    assert person is not None
    cli.access_grant(
        user=pending.id, person=person.id, role="caregiver", actor_user=admin.id, can_approve=True
    )
    grant = cli_session.scalar(
        select(AccessGrant).where(
            AccessGrant.user_account_id == pending.id, AccessGrant.role == "caregiver"
        )
    )
    assert grant is not None
    cli.access_revoke(grant.id, actor_user=admin.id)
    grant = cli_session.get(AccessGrant, grant.id)
    assert grant is not None
    assert grant.revoked_at is not None
    with pytest.raises(typer.BadParameter):
        cli.access_grant(user=uuid4(), person=person.id, role="owner", actor_user=admin.id)


def test_cli_import_and_inspection_workflow(cli_session: Session, tmp_path: Path) -> None:
    owner = identity(cli_session, "dev-owner")
    csv_path = tmp_path / "synthetic.csv"
    csv_path.write_text(
        "person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier\nkevin-demo,step_count,2026-08-01T12:00:00-04:00,42,count,measured,consumer_device,cli-steps\n",
        encoding="utf-8",
    )
    cli.import_csv_command(
        csv_path,
        person_external_reference="kevin-demo",
        source_system="manual-csv",
        actor_user=owner.id,
    )
    run = cli_session.scalar(select(ProcessingRun))
    assert run is not None
    cli.artifacts_list(actor_user=owner.id)
    cli.processing_show(run.id, actor_user=owner.id)
    cli.candidates_list(run.id, actor_user=owner.id)
    with pytest.raises(typer.BadParameter):
        cli.processing_show(uuid4(), actor_user=owner.id)


def test_cli_candidate_review_commands(cli_session: Session, tmp_path: Path) -> None:
    owner = identity(cli_session, "dev-owner")
    csv_path = tmp_path / "review.csv"
    csv_path.write_text(
        "person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier\nkevin-demo,body_weight,2026-08-01T12:00:00-04:00,200,lb,measured,consumer_device,cli-review-base\n",
        encoding="utf-8",
    )
    cli.import_csv_command(
        csv_path,
        person_external_reference="kevin-demo",
        source_system="manual-csv",
        actor_user=owner.id,
    )
    original = cli_session.scalar(select(CandidateRecord))
    assert original is not None and original.normalized_candidate_json is not None
    normalized = dict(original.normalized_candidate_json)
    normalized["source_record_identifier"] = "cli-approve"
    review = CandidateRecord(
        processing_run_id=original.processing_run_id,
        subject_person_id=original.subject_person_id,
        candidate_type="health_observation",
        source_locator="manual:approve",
        status="awaiting_review",
        raw_candidate_json={},
        normalized_candidate_json=normalized,
    )
    cli_session.add(review)
    cli_session.commit()
    cli.candidates_approve(review.id, actor_user=owner.id)
    review = cli_session.get(CandidateRecord, review.id)
    assert review is not None
    assert review.status == "promoted"
    normalized["source_record_identifier"] = "cli-reject"
    reject = CandidateRecord(
        processing_run_id=original.processing_run_id,
        subject_person_id=original.subject_person_id,
        candidate_type="health_observation",
        source_locator="manual:reject",
        status="awaiting_review",
        raw_candidate_json={},
        normalized_candidate_json=normalized,
    )
    cli_session.add(reject)
    cli_session.commit()
    cli.candidates_reject(reject.id, actor_user=owner.id, reason="Synthetic rejection")
    reject = cli_session.get(CandidateRecord, reject.id)
    assert reject is not None
    assert reject.status == "rejected"


def test_cli_requires_explicit_active_actor(cli_session: Session) -> None:
    pending = identity(cli_session, "dev-pending")
    with pytest.raises(typer.BadParameter, match="active"):
        cli.users_list(actor_user=pending.id)
