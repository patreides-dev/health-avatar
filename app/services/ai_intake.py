from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import HealthExtractionFact, HealthExtractionRequest
from app.ai.providers import (
    OUTPUT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_NAME,
    PROMPT_VERSION,
    ExtractionProvider,
    ProviderError,
)
from app.ai.registry import HealthFactDefinition, registry
from app.core.config import Settings
from app.models import (
    AIIntakeRequest,
    AIProcessingConsent,
    AuditEvent,
    CandidateRecord,
    ExerciseMetric,
    ExerciseMetricDefinition,
    ExerciseSession,
    ExerciseType,
    HealthObservation,
    ObservationType,
    Person,
    ProcessingRun,
    ProposedFactRevision,
    ProposedHealthFact,
    ProposedHealthFactGroup,
    SourceArtifact,
    SourceSystem,
    ValidationIssue,
)
from app.models.enums import AIIntakeStatus, CandidateStatus, FactStatus, ProcessingStatus
from app.services.auth import Actor
from app.services.authorization import Action, authorize
from app.services.catalog import ensure_ai_catalog
from app.services.ingestion import accept_artifact
from app.services.storage import ArtifactStorage


class AIIntakeError(ValueError):
    pass


SENSITIVITY_ORDER = {
    "exercise": 1,
    "nutrition": 1,
    "general_health": 2,
    "biometric": 3,
    "clinical": 4,
    "highly_sensitive_clinical": 5,
}


def _source_system(session: Session) -> SourceSystem:
    ensure_ai_catalog(session)
    source = session.scalar(select(SourceSystem).where(SourceSystem.name == "ai-intake"))
    if source is None:
        source = SourceSystem(
            name="ai-intake",
            source_type="ai_assisted_intake",
            vendor="Health Avatar",
            description="Reviewed AI-assisted or manual health intake.",
        )
        session.add(source)
        session.flush()
    return source


def _validate_cloud_policy(settings: Settings, sensitivity: str, consent: bool) -> None:
    if not consent:
        raise AIIntakeError("Affirmative processing consent is required")
    if settings.ai_provider != "mock" and not settings.cloud_ai_enabled:
        raise AIIntakeError("Cloud AI processing is disabled")
    maximum = SENSITIVITY_ORDER.get(settings.openai_max_sensitivity, 0)
    requested = SENSITIVITY_ORDER.get(sensitivity, maximum + 1)
    if settings.ai_provider != "mock" and requested > maximum:
        raise AIIntakeError("Sensitivity exceeds provider policy")


def _set_typed_value(model: ProposedHealthFact, proposal: HealthExtractionFact) -> None:
    value = proposal.value
    if value is None:
        return
    if proposal.value_type == "numeric":
        model.numeric_value = Decimal(str(value))
    elif proposal.value_type == "boolean":
        model.boolean_value = bool(value)
    elif proposal.value_type == "date":
        model.date_value = value if isinstance(value, date) else date.fromisoformat(str(value))
    elif proposal.value_type == "datetime":
        model.datetime_value = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    else:
        model.text_value = str(value)


def _fact_status(
    proposal: HealthExtractionFact, definition: HealthFactDefinition | None
) -> tuple[str, str | None, list[tuple[str, str, str]]]:
    issues: list[tuple[str, str, str]] = []
    if definition is None:
        return (
            FactStatus.UNSUPPORTED,
            None,
            [("warning", "unsupported_fact", "Fact has no registered canonical mapping")],
        )
    if proposal.value is None:
        return (
            FactStatus.UNRESOLVED,
            definition.canonical_target,
            [("error", "missing_value", "Fact has no resolved value")],
        )
    if proposal.value_type != definition.expected_value_type:
        return (
            FactStatus.INVALID,
            definition.canonical_target,
            [("error", "invalid_value_type", "Fact value type does not match its definition")],
        )
    if proposal.unit is None:
        return (
            FactStatus.INVALID,
            definition.canonical_target,
            [("error", "missing_unit", "Numeric fact requires an explicit unit")],
        )
    if proposal.unit not in definition.allowed_units:
        return (
            FactStatus.INVALID,
            definition.canonical_target,
            [("error", "invalid_unit", "Unit is not allowed for this fact")],
        )
    return FactStatus.AWAITING_REVIEW, definition.canonical_target, issues


def submit_intake(
    session: Session,
    *,
    person_id: UUID,
    actor: Actor,
    modality: str,
    purpose: str,
    user_text: str | None,
    content: bytes | None,
    provider_content: bytes | None,
    filename: str | None,
    media_type: str,
    sensitivity: str,
    consent: bool,
    provider: ExtractionProvider,
    storage: ArtifactStorage,
    settings: Settings,
) -> AIIntakeRequest:
    authorize(session, actor, person_id, Action.SUBMIT)
    _validate_cloud_policy(settings, sensitivity, consent)
    source = _source_system(session)
    artifact_content = content if content is not None else (user_text or "").encode("utf-8")
    artifact = accept_artifact(
        session,
        content=artifact_content,
        filename=filename,
        media_type=media_type,
        artifact_kind="image" if content is not None else "text",
        sensitivity=sensitivity,
        person=session.get_one(Person, person_id),
        source_system=source,
        actor=actor,
        storage=storage,
        settings=settings,
    )
    existing = session.scalar(
        select(AIIntakeRequest).where(
            AIIntakeRequest.source_artifact_id == artifact.id,
            AIIntakeRequest.provider_name == provider.name,
            AIIntakeRequest.prompt_version == PROMPT_VERSION,
        )
    )
    if existing is not None:
        return existing
    intake = AIIntakeRequest(
        person_id=person_id,
        submitted_by_user_account_id=actor.user_id,
        source_artifact_id=artifact.id,
        input_modality=modality,
        intake_purpose=purpose,
        user_context_text=user_text,
        provider_name=provider.name,
        model_name=provider.model_name,
        prompt_template_name=PROMPT_TEMPLATE_NAME,
        prompt_version=PROMPT_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        status=AIIntakeStatus.PROCESSING,
    )
    session.add(intake)
    session.flush()
    session.add(
        AIProcessingConsent(
            ai_intake_request_id=intake.id,
            user_account_id=actor.user_id,
            source_artifact_id=artifact.id,
            provider_name=provider.name,
            model_name=provider.model_name,
            purpose=purpose,
            policy_version=settings.ai_consent_policy_version,
        )
    )
    run = ProcessingRun(
        source_artifact_id=artifact.id,
        adapter_name=f"ai:{provider.name}",
        adapter_version=PROMPT_VERSION,
        schema_version=OUTPUT_SCHEMA_VERSION,
        requested_by_user_account_id=actor.user_id,
        status=ProcessingStatus.PROCESSING,
        configuration_json={"purpose": purpose, "modality": modality},
    )
    session.add(run)
    session.flush()
    intake.processing_run_id = run.id
    try:
        response = provider.extract_health_facts(
            HealthExtractionRequest(
                modality=modality,
                purpose=purpose,
                user_text=user_text,
                media_type=media_type,
                artifact_bytes=provider_content if provider_content is not None else content,
                sensitivity=sensitivity,
            )
        )
    except ProviderError as exc:
        intake.status = AIIntakeStatus.FAILED
        intake.error_code = "provider_error"
        intake.completed_at = datetime.now(UTC)
        run.status = ProcessingStatus.FAILED
        run.error_summary = str(exc)
        run.completed_at = intake.completed_at
        artifact.processing_status = "failed"
        session.commit()
        raise AIIntakeError(str(exc)) from exc

    groups: dict[str, ProposedHealthFactGroup] = {}
    for draft in response.detected_fact_groups:
        group = ProposedHealthFactGroup(
            ai_intake_request_id=intake.id,
            processing_run_id=run.id,
            subject_person_id=person_id,
            group_identifier=draft.group_identifier,
            group_type=draft.group_type,
            display_name=draft.display_name,
            status=FactStatus.AWAITING_REVIEW,
        )
        session.add(group)
        groups[draft.group_identifier] = group
    session.flush()
    issue_count = 0
    for index, proposal in enumerate(response.proposed_health_facts, start=1):
        definition = registry.get(proposal.fact_code)
        fact_status, target, issues = _fact_status(proposal, definition)
        candidate = CandidateRecord(
            processing_run_id=run.id,
            subject_person_id=person_id,
            candidate_type="proposed_health_fact",
            source_locator=proposal.source_locator or f"fact:{index}",
            status=(
                CandidateStatus.INVALID
                if fact_status == FactStatus.INVALID
                else CandidateStatus.AWAITING_REVIEW
            ),
            confidence=proposal.confidence,
            raw_candidate_json=proposal.model_dump(mode="json"),
            normalized_candidate_json=proposal.model_dump(mode="json"),
        )
        session.add(candidate)
        session.flush()
        fact_group = groups.get(proposal.group_identifier) if proposal.group_identifier else None
        fact = ProposedHealthFact(
            processing_run_id=run.id,
            candidate_record_id=candidate.id,
            fact_group_id=fact_group.id if fact_group is not None else None,
            subject_person_id=person_id,
            fact_category=definition.category if definition else "unknown",
            fact_code=proposal.fact_code,
            display_name=proposal.display_name,
            value_type=proposal.value_type,
            original_value_text=str(proposal.value) if proposal.value is not None else None,
            unit=proposal.unit,
            original_unit=proposal.unit,
            reference_range_low=proposal.reference_range_low,
            reference_range_high=proposal.reference_range_high,
            reference_range_text=proposal.reference_range_text,
            observed_at=proposal.observed_at,
            confidence=proposal.confidence,
            source_label=proposal.source_label,
            source_locator=proposal.source_locator,
            interpretation_notes=proposal.interpretation_notes,
            canonical_target_type=target,
            canonical_status=fact_status,
            original_proposal_json=proposal.model_dump(mode="json"),
        )
        _set_typed_value(fact, proposal)
        session.add(fact)
        for severity, code, message in issues:
            issue_count += 1
            session.add(
                ValidationIssue(
                    processing_run_id=run.id,
                    candidate_record_id=candidate.id,
                    severity=severity,
                    issue_code=code,
                    message=message,
                    source_locator=candidate.source_locator,
                    details_json={"fact_code": proposal.fact_code},
                )
            )
    for warning in response.warnings:
        issue_count += 1
        session.add(
            ValidationIssue(
                processing_run_id=run.id,
                severity="warning",
                issue_code="provider_warning",
                message=warning,
                details_json={},
            )
        )
    intake.raw_model_response_json = response.model_dump(mode="json")
    intake.submission_summary = response.submission_summary
    intake.unresolved_content = response.unresolved_content
    intake.overall_confidence = response.overall_confidence
    intake.status = AIIntakeStatus.AWAITING_REVIEW
    intake.completed_at = datetime.now(UTC)
    run.status = ProcessingStatus.AWAITING_REVIEW
    run.candidate_count = len(response.proposed_health_facts)
    run.review_required_count = len(response.proposed_health_facts)
    run.rejected_count = sum(
        fact.canonical_status in {FactStatus.INVALID, FactStatus.UNSUPPORTED}
        for fact in session.scalars(
            select(ProposedHealthFact).where(ProposedHealthFact.processing_run_id == run.id)
        )
    )
    run.completed_at = intake.completed_at
    artifact.processing_status = "awaiting_review"
    session.add(
        AuditEvent(
            actor_user_account_id=actor.user_id,
            action="ai_intake.submit",
            target_type="ai_intake_request",
            target_id=intake.id,
            details_json={"provider": provider.name, "fact_count": run.candidate_count},
        )
    )
    session.commit()
    session.refresh(intake)
    return intake


def _fact_snapshot(fact: ProposedHealthFact) -> dict[str, object]:
    return {
        "numeric_value": str(fact.numeric_value) if fact.numeric_value is not None else None,
        "text_value": fact.text_value,
        "unit": fact.unit,
        "observed_at": fact.observed_at.isoformat() if fact.observed_at else None,
        "status": fact.canonical_status,
    }


def revise_fact(
    session: Session,
    *,
    fact: ProposedHealthFact,
    actor: Actor,
    numeric_value: Decimal | None,
    unit: str | None,
    observed_at: datetime | None,
    remove: bool,
    reason: str | None,
) -> ProposedHealthFact:
    authorize(session, actor, fact.subject_person_id, Action.APPROVE)
    before = _fact_snapshot(fact)
    if remove:
        fact.canonical_status = FactStatus.REJECTED
    else:
        if numeric_value is not None:
            fact.numeric_value = numeric_value
        if unit is not None:
            fact.unit = unit
        if observed_at is not None:
            fact.observed_at = observed_at
        definition = registry.get(fact.fact_code)
        if definition is None:
            fact.canonical_status = FactStatus.UNSUPPORTED
        elif fact.numeric_value is None or fact.unit not in definition.allowed_units:
            fact.canonical_status = FactStatus.INVALID
        else:
            fact.canonical_status = FactStatus.AWAITING_REVIEW
    session.add(
        ProposedFactRevision(
            proposed_health_fact_id=fact.id,
            actor_user_account_id=actor.user_id,
            action="remove" if remove else "correct",
            before_json=before,
            after_json=_fact_snapshot(fact),
            reason=reason,
        )
    )
    session.commit()
    session.refresh(fact)
    return fact


def add_reviewed_fact(
    session: Session,
    *,
    intake: AIIntakeRequest,
    actor: Actor,
    fact_code: str,
    numeric_value: Decimal,
    unit: str,
    observed_at: datetime | None,
    group_id: UUID | None,
    reason: str | None,
) -> ProposedHealthFact:
    authorize(session, actor, intake.person_id, Action.APPROVE)
    if intake.processing_run_id is None:
        raise AIIntakeError("Intake has no processing run")
    definition = registry.get(fact_code)
    if definition is None or unit not in definition.allowed_units:
        raise AIIntakeError("Added fact is unsupported or has an invalid unit")
    if group_id is not None:
        group = session.get(ProposedHealthFactGroup, group_id)
        if group is None or group.processing_run_id != intake.processing_run_id:
            raise AIIntakeError("Fact group is invalid")
    candidate = CandidateRecord(
        processing_run_id=intake.processing_run_id,
        subject_person_id=intake.person_id,
        candidate_type="proposed_health_fact",
        source_locator="reviewer_added",
        status=CandidateStatus.AWAITING_REVIEW,
        confidence=None,
        raw_candidate_json={"added_by_user": True},
        normalized_candidate_json={
            "fact_code": fact_code,
            "numeric_value": str(numeric_value),
            "unit": unit,
        },
    )
    session.add(candidate)
    session.flush()
    fact = ProposedHealthFact(
        processing_run_id=intake.processing_run_id,
        candidate_record_id=candidate.id,
        fact_group_id=group_id,
        subject_person_id=intake.person_id,
        fact_category=definition.category,
        fact_code=fact_code,
        display_name=definition.display_name,
        value_type="numeric",
        numeric_value=numeric_value,
        unit=unit,
        original_unit=None,
        observed_at=observed_at,
        source_label="Added during human review",
        source_locator="reviewer_added",
        canonical_target_type=definition.canonical_target,
        canonical_status=FactStatus.AWAITING_REVIEW,
        original_proposal_json={"added_by_user": True},
    )
    session.add(fact)
    session.flush()
    session.add(
        ProposedFactRevision(
            proposed_health_fact_id=fact.id,
            actor_user_account_id=actor.user_id,
            action="add",
            before_json={},
            after_json=_fact_snapshot(fact),
            reason=reason,
        )
    )
    run = session.get_one(ProcessingRun, intake.processing_run_id)
    run.candidate_count += 1
    run.review_required_count += 1
    session.commit()
    session.refresh(fact)
    return fact


OBSERVATION_CODE = {
    "blood_pressure_systolic": "systolic_blood_pressure",
    "blood_pressure_diastolic": "diastolic_blood_pressure",
}


def _promote_observation(
    session: Session, fact: ProposedHealthFact, intake: AIIntakeRequest, actor: Actor
) -> HealthObservation:
    existing = (
        session.get(HealthObservation, fact.promoted_record_id) if fact.promoted_record_id else None
    )
    if existing is not None:
        return existing
    if fact.numeric_value is None or fact.unit is None or fact.observed_at is None:
        raise AIIntakeError(
            "Observation requires a numeric value, unit, and reviewed observation time"
        )
    observation_type = session.scalar(
        select(ObservationType).where(
            ObservationType.code == OBSERVATION_CODE.get(fact.fact_code, fact.fact_code)
        )
    )
    artifact = session.get_one(SourceArtifact, intake.source_artifact_id)
    source = session.get_one(SourceSystem, artifact.source_system_id)
    if observation_type is None or fact.unit != observation_type.default_unit:
        raise AIIntakeError("Canonical observation type or unit is not configured")
    observation = HealthObservation(
        person_id=fact.subject_person_id,
        observation_type_id=observation_type.id,
        observed_at=fact.observed_at,
        numeric_value=fact.numeric_value,
        unit=fact.unit,
        source_system_id=source.id,
        source_artifact_id=artifact.id,
        processing_run_id=fact.processing_run_id,
        created_by_user_account_id=intake.submitted_by_user_account_id,
        approved_by_user_account_id=actor.user_id,
        adapter_name=f"ai:{intake.provider_name}",
        adapter_version=intake.prompt_version,
        source_record_identifier=f"ai-fact:{fact.id}",
        measurement_method="reported",
        reliability_classification="user_confirmed_ai_extraction",
    )
    session.add(observation)
    session.flush()
    fact.promoted_record_type = "health_observation"
    fact.promoted_record_id = observation.id
    fact.canonical_status = FactStatus.PROMOTED
    return observation


def _duration_seconds(value: Decimal, unit: str) -> int:
    multiplier = {"s": Decimal(1), "min": Decimal(60), "hour": Decimal(3600)}[unit]
    return int(value * multiplier)


def _promote_exercise_group(
    session: Session,
    group: ProposedHealthFactGroup,
    intake: AIIntakeRequest,
    facts: list[ProposedHealthFact],
    actor: Actor,
) -> ExerciseSession:
    existing = session.scalar(
        select(ExerciseSession).where(ExerciseSession.fact_group_id == group.id)
    )
    if existing is not None:
        return existing
    exercise_type = session.scalar(select(ExerciseType).where(ExerciseType.code == "elliptical"))
    if exercise_type is None:
        raise AIIntakeError("Exercise catalog is not configured")
    duration = next((fact for fact in facts if fact.fact_code == "exercise_duration"), None)
    artifact = session.get_one(SourceArtifact, intake.source_artifact_id)
    exercise = ExerciseSession(
        person_id=intake.person_id,
        exercise_type_id=exercise_type.id,
        source_artifact_id=artifact.id,
        processing_run_id=intake.processing_run_id,
        fact_group_id=group.id,
        entered_by_user_account_id=intake.submitted_by_user_account_id,
        confirmed_by_user_account_id=actor.user_id,
        started_at=None,
        duration_seconds=_duration_seconds(duration.numeric_value, duration.unit)
        if duration and duration.numeric_value is not None and duration.unit
        else None,
        source_measurement_reliability="machine_display_user_confirmed",
    )
    session.add(exercise)
    session.flush()
    for fact in facts:
        definition = session.scalar(
            select(ExerciseMetricDefinition).where(
                ExerciseMetricDefinition.code == fact.fact_code.removeprefix("exercise_")
            )
        )
        if definition and fact.numeric_value is not None and fact.unit:
            session.add(
                ExerciseMetric(
                    exercise_session_id=exercise.id,
                    metric_definition_id=definition.id,
                    numeric_value=fact.numeric_value,
                    unit=fact.unit,
                    extraction_confidence=fact.confidence,
                    source_measurement_reliability="machine_display",
                    user_confirmed=True,
                    proposed_health_fact_id=fact.id,
                )
            )
            fact.promoted_record_type = "exercise_session"
            fact.promoted_record_id = exercise.id
            fact.canonical_status = FactStatus.PROMOTED
    group.status = FactStatus.PROMOTED
    return exercise


def _confirm_intake(session: Session, *, intake: AIIntakeRequest, actor: Actor) -> AIIntakeRequest:
    authorize(session, actor, intake.person_id, Action.APPROVE)
    if intake.processing_run_id is None:
        raise AIIntakeError("Intake has no processing run")
    facts = list(
        session.scalars(
            select(ProposedHealthFact)
            .where(ProposedHealthFact.processing_run_id == intake.processing_run_id)
            .order_by(ProposedHealthFact.created_at, ProposedHealthFact.id)
        )
    )
    for fact in facts:
        if fact.canonical_status == FactStatus.INVALID:
            raise AIIntakeError("Invalid facts must be corrected or removed before confirmation")
    groups = list(
        session.scalars(
            select(ProposedHealthFactGroup).where(
                ProposedHealthFactGroup.processing_run_id == intake.processing_run_id
            )
        )
    )
    for group in groups:
        group_facts = [fact for fact in facts if fact.fact_group_id == group.id]
        if group.group_type == "exercise_session":
            _promote_exercise_group(session, group, intake, group_facts, actor)
        else:
            group.status = FactStatus.CONFIRMED
    for fact in facts:
        if fact.canonical_status in {
            FactStatus.UNSUPPORTED,
            FactStatus.UNRESOLVED,
            FactStatus.REJECTED,
            FactStatus.PROMOTED,
        }:
            continue
        fact.confirmed_by_user_account_id = actor.user_id
        fact.confirmed_at = fact.confirmed_at or datetime.now(UTC)
        if fact.canonical_target_type == "health_observation":
            _promote_observation(session, fact, intake, actor)
        elif fact.canonical_target_type is None:
            fact.canonical_status = FactStatus.CONFIRMED
    intake.status = AIIntakeStatus.COMPLETED
    run = session.get_one(ProcessingRun, intake.processing_run_id)
    run.status = ProcessingStatus.COMPLETED
    run.accepted_count = sum(fact.canonical_status == FactStatus.PROMOTED for fact in facts)
    run.review_required_count = 0
    session.add(
        AuditEvent(
            actor_user_account_id=actor.user_id,
            action="ai_intake.confirm",
            target_type="ai_intake_request",
            target_id=intake.id,
            details_json={"promoted_count": run.accepted_count},
        )
    )
    session.flush()
    return intake


def confirm_intake(session: Session, *, intake: AIIntakeRequest, actor: Actor) -> AIIntakeRequest:
    try:
        with session.begin_nested():
            result = _confirm_intake(session, intake=intake, actor=actor)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(result)
    return result


def reject_intake(
    session: Session, *, intake: AIIntakeRequest, actor: Actor, reason: str | None
) -> AIIntakeRequest:
    authorize(session, actor, intake.person_id, Action.APPROVE)
    if intake.processing_run_id:
        for fact in session.scalars(
            select(ProposedHealthFact).where(
                ProposedHealthFact.processing_run_id == intake.processing_run_id
            )
        ):
            if fact.canonical_status != FactStatus.PROMOTED:
                fact.canonical_status = FactStatus.REJECTED
        run = session.get_one(ProcessingRun, intake.processing_run_id)
        run.status = ProcessingStatus.CANCELLED
    intake.status = AIIntakeStatus.REJECTED
    session.add(
        AuditEvent(
            actor_user_account_id=actor.user_id,
            action="ai_intake.reject",
            target_type="ai_intake_request",
            target_id=intake.id,
            details_json={"reason": reason},
        )
    )
    session.commit()
    session.refresh(intake)
    return intake
