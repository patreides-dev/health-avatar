from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CandidateRecord,
    HealthObservation,
    ObservationType,
    ProcessingRun,
    SourceArtifact,
)
from app.models.enums import CandidateStatus
from app.services.auth import Actor
from app.services.authorization import Action, AuthorizationError, authorize


class PromotionError(ValueError):
    pass


class ObservationCandidate(BaseModel):
    observation_type_id: UUID
    observed_at: datetime
    numeric_value: Decimal
    unit: str
    measurement_method: str
    reliability_classification: str
    source_record_identifier: str
    source_row_number: int


def promote_candidate(
    session: Session, *, candidate: CandidateRecord, actor: Actor, automatic: bool = False
) -> HealthObservation:
    existing = session.scalar(
        select(HealthObservation).where(HealthObservation.candidate_record_id == candidate.id)
    )
    if existing is not None:
        return existing
    if (
        candidate.candidate_type != "health_observation"
        or candidate.normalized_candidate_json is None
    ):
        raise PromotionError("Unsupported or incomplete candidate type")
    if candidate.subject_person_id is None:
        raise PromotionError("Candidate subject is unresolved")
    if candidate.status not in {CandidateStatus.APPROVED, CandidateStatus.AWAITING_REVIEW}:
        raise PromotionError("Candidate is not eligible for promotion")
    authorize(
        session, actor, candidate.subject_person_id, Action.SUBMIT if automatic else Action.APPROVE
    )
    normalized = ObservationCandidate.model_validate(candidate.normalized_candidate_json)
    observation_type = session.get(ObservationType, normalized.observation_type_id)
    if observation_type is None or observation_type.default_unit != normalized.unit:
        raise PromotionError("Observation type or unit is invalid")
    run = session.get(ProcessingRun, candidate.processing_run_id)
    if run is None:
        raise PromotionError("Processing run is missing")
    artifact = session.get(SourceArtifact, run.source_artifact_id)
    if artifact is None or artifact.source_system_id is None:
        raise PromotionError("Source artifact has no source system")
    observation = HealthObservation(
        person_id=candidate.subject_person_id,
        observation_type=observation_type,
        observed_at=normalized.observed_at,
        numeric_value=normalized.numeric_value,
        unit=normalized.unit,
        source_system_id=artifact.source_system_id,
        source_artifact_id=artifact.id,
        processing_run_id=run.id,
        candidate_record_id=candidate.id,
        created_by_user_account_id=artifact.submitted_by_user_account_id,
        approved_by_user_account_id=actor.user_id,
        adapter_name=run.adapter_name,
        adapter_version=run.adapter_version,
        source_record_identifier=normalized.source_record_identifier,
        source_row_number=normalized.source_row_number,
        raw_source_row_json=candidate.raw_candidate_json,
        measurement_method=normalized.measurement_method,
        reliability_classification=normalized.reliability_classification,
    )
    session.add(observation)
    candidate.status = CandidateStatus.PROMOTED
    if candidate.approved_at is None:
        candidate.approved_at = datetime.now(UTC)
        candidate.approved_by_user_account_id = actor.user_id
    try:
        session.flush()
    except IntegrityError as exc:
        raise PromotionError("Canonical observation conflicts with existing provenance") from exc
    return observation


def approve_candidate(
    session: Session, *, candidate: CandidateRecord, actor: Actor
) -> HealthObservation:
    if candidate.status == CandidateStatus.PROMOTED:
        if candidate.subject_person_id is None:
            raise PromotionError("Candidate subject is unresolved")
        authorize(session, actor, candidate.subject_person_id, Action.APPROVE)
        return promote_candidate(session, candidate=candidate, actor=actor)
    if candidate.status == CandidateStatus.INVALID:
        raise PromotionError("Invalid candidate cannot be approved")
    if candidate.subject_person_id is None:
        raise PromotionError("Candidate subject is unresolved")
    authorize(session, actor, candidate.subject_person_id, Action.APPROVE)
    candidate.status = CandidateStatus.APPROVED
    candidate.approved_by_user_account_id = actor.user_id
    candidate.approved_at = datetime.now(UTC)
    observation = promote_candidate(session, candidate=candidate, actor=actor)
    session.commit()
    session.refresh(observation)
    return observation


def reject_candidate(
    session: Session, *, candidate: CandidateRecord, actor: Actor, reason: str | None
) -> None:
    if candidate.subject_person_id is None:
        raise AuthorizationError("Resource not found")
    authorize(session, actor, candidate.subject_person_id, Action.APPROVE)
    if candidate.status == CandidateStatus.PROMOTED:
        raise PromotionError("Promoted candidate cannot be rejected")
    candidate.status = CandidateStatus.REJECTED
    candidate.rejected_by_user_account_id = actor.user_id
    candidate.rejected_at = datetime.now(UTC)
    candidate.rejection_reason = reason
    session.commit()
