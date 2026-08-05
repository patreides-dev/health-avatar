# ruff: noqa: E501
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AccessGrant,
    CandidateRecord,
    Household,
    HouseholdMembership,
    Person,
    SourceSystem,
    UserAccount,
)
from app.services.auth import Actor
from app.services.authorization import Action, AuthorizationError, authorize
from app.services.ingestion import ingest_csv
from app.services.storage import LocalArtifactStorage

CSV = b"person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier\nkevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,review-base\n"


def account(session: Session, subject: str) -> UserAccount:
    value = session.scalar(select(UserAccount).where(UserAccount.provider_subject == subject))
    assert value is not None
    return value


def test_roles_revocation_and_admin_non_implication(seeded_session: Session) -> None:
    person = seeded_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    assert person is not None
    viewer = account(seeded_session, "dev-viewer")
    authorize(seeded_session, Actor(viewer.id), person.id, Action.VIEW)
    with pytest.raises(AuthorizationError):
        authorize(seeded_session, Actor(viewer.id), person.id, Action.SUBMIT)
    admin = account(seeded_session, "dev-admin")
    with pytest.raises(AuthorizationError):
        authorize(seeded_session, Actor(admin.id, True), person.id, Action.VIEW)
    grant = seeded_session.scalar(
        select(AccessGrant).where(AccessGrant.user_account_id == viewer.id)
    )
    assert grant is not None
    grant.revoked_at = datetime.now(UTC)
    seeded_session.commit()
    with pytest.raises(AuthorizationError):
        authorize(seeded_session, Actor(viewer.id), person.id, Action.VIEW)


def test_household_membership_never_grants_access(seeded_session: Session) -> None:
    outsider = Person(
        external_reference="household-only", preferred_name="Household Only", timezone="UTC"
    )
    household = Household(name="Synthetic household")
    seeded_session.add_all([outsider, household])
    seeded_session.flush()
    seeded_session.add(
        HouseholdMembership(
            household_id=household.id, person_id=outsider.id, relationship_label="relative"
        )
    )
    seeded_session.commit()
    owner = account(seeded_session, "dev-owner")
    with pytest.raises(AuthorizationError):
        authorize(seeded_session, Actor(owner.id), outsider.id, Action.VIEW)


def create_review_candidate(
    session: Session, tmp_path: Path, status: str = "awaiting_review"
) -> CandidateRecord:
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    source = session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv"))
    owner = account(session, "dev-owner")
    settings = Settings(app_env="testing", artifact_storage_path=tmp_path / "artifacts")
    _, run, _ = ingest_csv(
        session,
        content=CSV,
        filename="review.csv",
        source_system=source,
        subject_person=person,
        actor=Actor(owner.id),
        storage=LocalArtifactStorage(settings.artifact_storage_path),
        settings=settings,
    )
    original = session.scalar(
        select(CandidateRecord).where(CandidateRecord.processing_run_id == run.id)
    )
    assert original is not None and original.normalized_candidate_json is not None
    normalized = dict(original.normalized_candidate_json)
    normalized["source_record_identifier"] = f"manual-{status}"
    candidate = CandidateRecord(
        processing_run_id=run.id,
        subject_person_id=person.id,
        candidate_type="health_observation",
        source_locator="manual:test",
        status=status,
        raw_candidate_json={"synthetic": "value"},
        normalized_candidate_json=normalized,
    )
    session.add(candidate)
    session.commit()
    return candidate


def test_viewer_cannot_approve_and_caregiver_can(
    client: TestClient,
    seeded_session: Session,
    login: Callable[[str], dict[str, str]],
    tmp_path: Path,
) -> None:
    candidate = create_review_candidate(seeded_session, tmp_path)
    headers = login("dev-viewer")
    assert (
        client.post(f"/api/v1/candidates/{candidate.id}/approve", headers=headers).status_code
        == 404
    )
    headers = login("dev-caregiver")
    response = client.post(f"/api/v1/candidates/{candidate.id}/approve", headers=headers)
    assert response.status_code == 200
    seeded_session.refresh(candidate)
    assert candidate.status == "promoted" and candidate.approved_at is not None
    observation_id = response.json()["observation_id"]
    repeated = client.post(f"/api/v1/candidates/{candidate.id}/approve", headers=headers)
    assert repeated.status_code == 200 and repeated.json()["observation_id"] == observation_id
    seeded_session.refresh(candidate)
    assert candidate.status == "promoted"


def test_invalid_candidate_cannot_be_approved(
    client: TestClient,
    seeded_session: Session,
    login: Callable[[str], dict[str, str]],
    tmp_path: Path,
) -> None:
    candidate = create_review_candidate(seeded_session, tmp_path, "invalid")
    response = client.post(f"/api/v1/candidates/{candidate.id}/approve", headers=login("dev-owner"))
    assert response.status_code == 409


def test_rejection_records_actor_and_reason(
    client: TestClient,
    seeded_session: Session,
    login: Callable[[str], dict[str, str]],
    tmp_path: Path,
) -> None:
    candidate = create_review_candidate(seeded_session, tmp_path)
    response = client.post(
        f"/api/v1/candidates/{candidate.id}/reject",
        json={"reason": "Synthetic warning needs correction"},
        headers=login("dev-owner"),
    )
    assert response.status_code == 200
    seeded_session.refresh(candidate)
    assert candidate.status == "rejected"
    assert candidate.rejected_by_user_account_id is not None
    assert candidate.rejection_reason == "Synthetic warning needs correction"
