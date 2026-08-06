from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ai.providers import ProviderError, provider_for
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    AccessGrant,
    AIIntakeRequest,
    AuditEvent,
    CandidateRecord,
    ExerciseMetric,
    ExerciseMetricDefinition,
    ExerciseSession,
    ExerciseType,
    ImportBatch,
    Person,
    ProcessingRun,
    ProposedHealthFact,
    SourceArtifact,
    SourceSystem,
    UserAccount,
)
from app.repositories.observations import count_statement, query_observations
from app.schemas.api import (
    AccessGrantCreate,
    AIIntakeRead,
    AITextIntakeCreate,
    ArtifactRead,
    CandidateRead,
    CandidateReject,
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    DeviceCreate,
    DeviceRead,
    ExerciseSessionCreate,
    ExerciseSessionRead,
    FactAddRequest,
    FactRevisionRequest,
    ImportBatchRead,
    IntakeRejectRequest,
    MeRead,
    ObservationPage,
    PersonCreate,
    PersonRead,
    ProcessingRunRead,
    ProposedHealthFactRead,
    SourceSystemCreate,
    SourceSystemRead,
)
from app.services.ai_intake import (
    AIIntakeError,
    add_reviewed_fact,
    confirm_intake,
    reject_intake,
    revise_fact,
    submit_intake,
)
from app.services.auth import Actor, get_actor, get_current_account, require_csrf
from app.services.authorization import (
    Action,
    AuthorizationError,
    authorize,
    require_system_administrator,
)
from app.services.catalog import ensure_ai_catalog
from app.services.entities import (
    ConflictError,
    RelatedEntityNotFoundError,
    create_device,
    create_device_assignment,
    create_person,
    create_source_system,
)
from app.services.image_safety import UnsafeImageError, create_safe_derivative
from app.services.ingestion import IngestionError, accept_artifact, ingest_csv, process_artifact
from app.services.promotion import PromotionError, approve_candidate, reject_candidate
from app.services.storage import LocalArtifactStorage

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]
CurrentActor = Annotated[Actor, Depends(get_actor)]
CSRF = Annotated[None, Depends(require_csrf)]


def not_found(entity: str = "Resource") -> HTTPException:
    return HTTPException(404, detail={"code": "not_found", "message": f"{entity} not found"})


def forbidden_as_not_found(exc: AuthorizationError) -> HTTPException:
    return not_found()


def person_action(session: Session, actor: Actor, person_id: UUID, action: Action) -> None:
    try:
        authorize(session, actor, person_id, action)
    except AuthorizationError as exc:
        raise forbidden_as_not_found(exc) from exc


@router.get("/me", response_model=MeRead)
def me(account: Annotated[UserAccount, Depends(get_current_account)]) -> UserAccount:
    return account


@router.get("/me/persons", response_model=list[PersonRead])
@router.get("/persons", response_model=list[PersonRead])
def list_persons(
    session: DB,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Person]:
    now = datetime.now(UTC)
    statement = (
        select(Person)
        .join(AccessGrant)
        .where(
            AccessGrant.user_account_id == actor.user_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
        )
        .distinct()
        .order_by(Person.created_at, Person.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


@router.post(
    "/persons",
    response_model=PersonRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def post_person(data: PersonCreate, session: DB, actor: CurrentActor) -> Person:
    try:
        require_system_administrator(actor)
        return create_person(session, data)
    except AuthorizationError as exc:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(exc)}) from exc
    except ConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc


@router.get("/persons/{person_id}", response_model=PersonRead)
def get_person(person_id: UUID, session: DB, actor: CurrentActor) -> Person:
    person_action(session, actor, person_id, Action.VIEW)
    person = session.get(Person, person_id)
    if person is None:
        raise not_found("Person")
    return person


@router.post(
    "/source-systems",
    response_model=SourceSystemRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_source_system(data: SourceSystemCreate, session: DB, actor: CurrentActor) -> SourceSystem:
    try:
        require_system_administrator(actor)
        return create_source_system(session, data)
    except AuthorizationError as exc:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(exc)}) from exc
    except ConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc


@router.post(
    "/devices", response_model=DeviceRead, status_code=201, dependencies=[Depends(require_csrf)]
)
def post_device(data: DeviceCreate, session: DB, actor: CurrentActor) -> object:
    try:
        require_system_administrator(actor)
        return create_device(session, data)
    except AuthorizationError as exc:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(exc)}) from exc
    except RelatedEntityNotFoundError as exc:
        raise not_found() from exc


@router.post(
    "/device-assignments",
    response_model=DeviceAssignmentRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_device_assignment(
    data: DeviceAssignmentCreate, session: DB, actor: CurrentActor
) -> object:
    try:
        require_system_administrator(actor)
        return create_device_assignment(session, data)
    except AuthorizationError as exc:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(exc)}) from exc
    except RelatedEntityNotFoundError as exc:
        raise not_found() from exc


def storage(settings: Settings) -> LocalArtifactStorage:
    return LocalArtifactStorage(settings.artifact_storage_path)


@router.post(
    "/artifacts", response_model=ArtifactRead, status_code=201, dependencies=[Depends(require_csrf)]
)
def post_artifact(
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    person_id: Annotated[UUID, Form()],
    source_system_id: Annotated[UUID, Form()],
    captured_at: Annotated[datetime | None, Form()] = None,
) -> SourceArtifact:
    person, source = session.get(Person, person_id), session.get(SourceSystem, source_system_id)
    if person is None or source is None:
        raise not_found()
    try:
        artifact = accept_artifact(
            session,
            content=file.file.read(settings.max_artifact_bytes + 1),
            filename=file.filename,
            media_type=file.content_type or "application/octet-stream",
            artifact_kind="file",
            sensitivity="general_health",
            person=person,
            source_system=source,
            actor=actor,
            storage=storage(settings),
            settings=settings,
        )
    except (AuthorizationError, IngestionError) as exc:
        if isinstance(exc, AuthorizationError):
            raise not_found() from exc
        raise HTTPException(422, detail={"code": "invalid_artifact", "message": str(exc)}) from exc
    artifact.captured_at = captured_at
    session.commit()
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: UUID, session: DB, actor: CurrentActor) -> SourceArtifact:
    artifact = session.get(SourceArtifact, artifact_id)
    if artifact is None or artifact.subject_person_id is None:
        raise not_found()
    person_action(session, actor, artifact.subject_person_id, Action.VIEW)
    return artifact


@router.post(
    "/artifacts/{artifact_id}/process",
    response_model=ProcessingRunRead,
    dependencies=[Depends(require_csrf)],
)
def post_process_artifact(
    artifact_id: UUID,
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
    adapter: str | None = None,
) -> ProcessingRun:
    artifact = session.get(SourceArtifact, artifact_id)
    if artifact is None or artifact.subject_person_id is None or artifact.storage_key is None:
        raise not_found()
    try:
        person_action(session, actor, artifact.subject_person_id, Action.SUBMIT)
        backend = storage(settings)
        return process_artifact(
            session,
            artifact=artifact,
            content=backend.get(artifact.storage_key),
            actor=actor,
            explicit_adapter=adapter,
        )
    except IngestionError as exc:
        raise HTTPException(422, detail={"code": "processing_failed", "message": str(exc)}) from exc


@router.post("/imports/csv", response_model=ImportBatchRead, dependencies=[Depends(require_csrf)])
def post_csv_import(
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    source_system_id: Annotated[UUID, Form()],
    person_external_reference: Annotated[str, Form()],
) -> ImportBatch:
    source = session.get(SourceSystem, source_system_id)
    person = session.scalar(
        select(Person).where(Person.external_reference == person_external_reference)
    )
    if source is None or person is None:
        raise not_found()
    try:
        _, _, batch = ingest_csv(
            session,
            content=file.file.read(settings.max_artifact_bytes + 1),
            filename=file.filename or "upload.csv",
            source_system=source,
            subject_person=person,
            actor=actor,
            storage=storage(settings),
            settings=settings,
        )
        return batch
    except AuthorizationError as exc:
        raise not_found() from exc
    except IngestionError as exc:
        raise HTTPException(422, detail={"code": "invalid_import", "message": str(exc)}) from exc


@router.get("/imports/{import_batch_id}", response_model=ImportBatchRead)
def get_import(import_batch_id: UUID, session: DB, actor: CurrentActor) -> ImportBatch:
    batch = session.get(ImportBatch, import_batch_id)
    if batch is None or batch.subject_person_id is None:
        raise not_found()
    person_action(session, actor, batch.subject_person_id, Action.VIEW)
    return batch


def authorized_run(session: Session, actor: Actor, run_id: UUID) -> ProcessingRun:
    run = session.get(ProcessingRun, run_id)
    artifact = session.get(SourceArtifact, run.source_artifact_id) if run else None
    if run is None or artifact is None or artifact.subject_person_id is None:
        raise not_found()
    person_action(session, actor, artifact.subject_person_id, Action.VIEW)
    return run


@router.get("/processing-runs/{run_id}", response_model=ProcessingRunRead)
def get_processing_run(run_id: UUID, session: DB, actor: CurrentActor) -> ProcessingRun:
    return authorized_run(session, actor, run_id)


@router.get("/processing-runs/{run_id}/candidates", response_model=list[CandidateRead])
def list_candidates(
    run_id: UUID,
    session: DB,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CandidateRecord]:
    authorized_run(session, actor, run_id)
    return list(
        session.scalars(
            select(CandidateRecord)
            .where(CandidateRecord.processing_run_id == run_id)
            .order_by(CandidateRecord.created_at, CandidateRecord.id)
            .limit(limit)
            .offset(offset)
        )
    )


@router.post("/candidates/{candidate_id}/approve", dependencies=[Depends(require_csrf)])
def post_approve(candidate_id: UUID, session: DB, actor: CurrentActor) -> dict[str, str]:
    candidate = session.get(CandidateRecord, candidate_id)
    if candidate is None:
        raise not_found()
    try:
        observation = approve_candidate(session, candidate=candidate, actor=actor)
    except AuthorizationError as exc:
        raise not_found() from exc
    except PromotionError as exc:
        raise HTTPException(409, detail={"code": "promotion_failed", "message": str(exc)}) from exc
    return {
        "candidate_id": str(candidate.id),
        "observation_id": str(observation.id),
        "status": candidate.status,
    }


@router.post("/candidates/{candidate_id}/reject", dependencies=[Depends(require_csrf)])
def post_reject(
    candidate_id: UUID, data: CandidateReject, session: DB, actor: CurrentActor
) -> dict[str, str]:
    candidate = session.get(CandidateRecord, candidate_id)
    if candidate is None:
        raise not_found()
    try:
        reject_candidate(session, candidate=candidate, actor=actor, reason=data.reason)
    except AuthorizationError as exc:
        raise not_found() from exc
    except PromotionError as exc:
        raise HTTPException(409, detail={"code": "rejection_failed", "message": str(exc)}) from exc
    return {"candidate_id": str(candidate.id), "status": candidate.status}


@router.get("/persons/{person_id}/observations", response_model=ObservationPage)
def get_observations(
    person_id: UUID,
    session: DB,
    actor: CurrentActor,
    observation_type: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    source_system_id: UUID | None = None,
    device_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ObservationPage:
    person_action(session, actor, person_id, Action.VIEW)
    statement = query_observations(
        session,
        person_id=person_id,
        observation_type=observation_type,
        observed_from=observed_from,
        observed_to=observed_to,
        source_system_id=source_system_id,
        device_id=device_id,
    )
    total = session.scalar(count_statement(statement)) or 0
    return ObservationPage(
        items=list(session.scalars(statement.limit(limit).offset(offset))),
        total=total,
        limit=limit,
        offset=offset,
    )


def intake_resource(
    session: Session, actor: Actor, intake_id: UUID, action: Action = Action.VIEW
) -> AIIntakeRequest:
    intake = session.get(AIIntakeRequest, intake_id)
    if intake is None:
        raise not_found()
    person_action(session, actor, intake.person_id, action)
    return intake


@router.post(
    "/persons/{person_id}/ai-intake/text",
    response_model=AIIntakeRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_text_intake(
    person_id: UUID,
    data: AITextIntakeCreate,
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AIIntakeRequest:
    try:
        return submit_intake(
            session,
            person_id=person_id,
            actor=actor,
            modality="text",
            purpose=data.purpose,
            user_text=data.text,
            content=None,
            provider_content=None,
            filename=None,
            media_type="text/plain; charset=utf-8",
            sensitivity=data.sensitivity,
            consent=data.consent,
            provider=provider_for(settings),
            storage=storage(settings),
            settings=settings,
        )
    except AuthorizationError as exc:
        raise not_found() from exc
    except (AIIntakeError, ProviderError) as exc:
        raise HTTPException(422, detail={"code": "ai_intake_failed", "message": str(exc)}) from exc


@router.post(
    "/persons/{person_id}/ai-intake/image",
    response_model=AIIntakeRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_image_intake(
    person_id: UUID,
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    consent: Annotated[bool, Form()],
    purpose: Annotated[str, Form()] = "general_health",
    context: Annotated[str | None, Form()] = None,
    sensitivity: Annotated[str, Form()] = "general_health",
) -> AIIntakeRequest:
    content = file.file.read(settings.max_artifact_bytes + 1)
    try:
        derivative = create_safe_derivative(
            content, file.content_type or "application/octet-stream", settings
        )
        return submit_intake(
            session,
            person_id=person_id,
            actor=actor,
            modality="mixed" if context else "image",
            purpose=purpose,
            user_text=context,
            content=content,
            provider_content=derivative.content,
            filename=file.filename,
            media_type=derivative.media_type,
            sensitivity=sensitivity,
            consent=consent,
            provider=provider_for(settings),
            storage=storage(settings),
            settings=settings,
        )
    except AuthorizationError as exc:
        raise not_found() from exc
    except (AIIntakeError, ProviderError, UnsafeImageError, IngestionError) as exc:
        raise HTTPException(422, detail={"code": "ai_intake_failed", "message": str(exc)}) from exc


@router.get("/ai-intake/{intake_id}", response_model=AIIntakeRead)
def get_ai_intake(intake_id: UUID, session: DB, actor: CurrentActor) -> AIIntakeRequest:
    return intake_resource(session, actor, intake_id)


@router.get("/persons/{person_id}/ai-intake", response_model=list[AIIntakeRead])
def list_ai_intakes(
    person_id: UUID,
    session: DB,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AIIntakeRequest]:
    person_action(session, actor, person_id, Action.VIEW)
    return list(
        session.scalars(
            select(AIIntakeRequest)
            .where(AIIntakeRequest.person_id == person_id)
            .order_by(AIIntakeRequest.created_at.desc(), AIIntakeRequest.id)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/ai-intake/{intake_id}/facts", response_model=list[ProposedHealthFactRead])
def list_intake_facts(
    intake_id: UUID, session: DB, actor: CurrentActor
) -> list[ProposedHealthFact]:
    intake = intake_resource(session, actor, intake_id)
    if intake.processing_run_id is None:
        return []
    return list(
        session.scalars(
            select(ProposedHealthFact)
            .where(ProposedHealthFact.processing_run_id == intake.processing_run_id)
            .order_by(ProposedHealthFact.created_at, ProposedHealthFact.id)
        )
    )


@router.post(
    "/ai-intake/{intake_id}/facts/{fact_id}/review",
    response_model=ProposedHealthFactRead,
    dependencies=[Depends(require_csrf)],
)
def post_fact_review(
    intake_id: UUID,
    fact_id: UUID,
    data: FactRevisionRequest,
    session: DB,
    actor: CurrentActor,
) -> ProposedHealthFact:
    intake = intake_resource(session, actor, intake_id, Action.APPROVE)
    fact = session.get(ProposedHealthFact, fact_id)
    if fact is None or fact.processing_run_id != intake.processing_run_id:
        raise not_found()
    try:
        return revise_fact(
            session,
            fact=fact,
            actor=actor,
            numeric_value=data.numeric_value,
            unit=data.unit,
            observed_at=data.observed_at,
            remove=data.remove,
            reason=data.reason,
        )
    except AuthorizationError as exc:
        raise not_found() from exc


@router.post(
    "/ai-intake/{intake_id}/facts",
    response_model=ProposedHealthFactRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_reviewed_fact(
    intake_id: UUID,
    data: FactAddRequest,
    session: DB,
    actor: CurrentActor,
) -> ProposedHealthFact:
    intake = intake_resource(session, actor, intake_id, Action.APPROVE)
    try:
        return add_reviewed_fact(
            session,
            intake=intake,
            actor=actor,
            fact_code=data.fact_code,
            numeric_value=data.numeric_value,
            unit=data.unit,
            observed_at=data.observed_at,
            group_id=data.group_id,
            reason=data.reason,
        )
    except (AIIntakeError, AuthorizationError) as exc:
        raise HTTPException(422, detail={"code": "invalid_fact", "message": str(exc)}) from exc


@router.post(
    "/ai-intake/{intake_id}/confirm",
    response_model=AIIntakeRead,
    dependencies=[Depends(require_csrf)],
)
def post_intake_confirm(intake_id: UUID, session: DB, actor: CurrentActor) -> AIIntakeRequest:
    intake = intake_resource(session, actor, intake_id, Action.APPROVE)
    try:
        return confirm_intake(session, intake=intake, actor=actor)
    except (AIIntakeError, AuthorizationError) as exc:
        raise HTTPException(
            409, detail={"code": "confirmation_failed", "message": str(exc)}
        ) from exc


@router.post(
    "/ai-intake/{intake_id}/reject",
    response_model=AIIntakeRead,
    dependencies=[Depends(require_csrf)],
)
def post_intake_reject(
    intake_id: UUID,
    data: IntakeRejectRequest,
    session: DB,
    actor: CurrentActor,
) -> AIIntakeRequest:
    intake = intake_resource(session, actor, intake_id, Action.APPROVE)
    return reject_intake(session, intake=intake, actor=actor, reason=data.reason)


@router.get("/artifacts/{artifact_id}/content", response_class=Response)
def get_artifact_content(
    artifact_id: UUID,
    session: DB,
    actor: CurrentActor,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    artifact = session.get(SourceArtifact, artifact_id)
    if artifact is None or artifact.subject_person_id is None or artifact.storage_key is None:
        raise not_found()
    person_action(session, actor, artifact.subject_person_id, Action.VIEW)
    return Response(
        content=storage(settings).get(artifact.storage_key),
        media_type=artifact.media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/persons/{person_id}/exercise-sessions",
    response_model=ExerciseSessionRead,
    status_code=201,
    dependencies=[Depends(require_csrf)],
)
def post_exercise_session(
    person_id: UUID,
    data: ExerciseSessionCreate,
    session: DB,
    actor: CurrentActor,
) -> ExerciseSession:
    person_action(session, actor, person_id, Action.SUBMIT)
    ensure_ai_catalog(session)
    exercise_type = session.scalar(
        select(ExerciseType).where(ExerciseType.code == data.exercise_type)
    )
    if exercise_type is None:
        raise HTTPException(
            422, detail={"code": "invalid_exercise_type", "message": "Unknown exercise type"}
        )
    entity = ExerciseSession(
        person_id=person_id,
        exercise_type_id=exercise_type.id,
        entered_by_user_account_id=actor.user_id,
        confirmed_by_user_account_id=actor.user_id,
        started_at=data.started_at,
        duration_seconds=data.duration_seconds,
        notes=data.notes,
        source_measurement_reliability="user_reported",
    )
    session.add(entity)
    session.flush()
    for item in data.metrics:
        definition = session.scalar(
            select(ExerciseMetricDefinition).where(ExerciseMetricDefinition.code == item.code)
        )
        if definition is None or item.unit not in definition.allowed_units_json:
            session.rollback()
            raise HTTPException(
                422, detail={"code": "invalid_exercise_metric", "message": "Invalid metric"}
            )
        session.add(
            ExerciseMetric(
                exercise_session_id=entity.id,
                metric_definition_id=definition.id,
                numeric_value=item.value,
                unit=item.unit,
                source_measurement_reliability="user_reported",
                user_confirmed=True,
            )
        )
    audit(session, actor, "exercise.create", "exercise_session", entity.id)
    session.commit()
    session.refresh(entity)
    return entity


@router.get("/persons/{person_id}/exercise-sessions", response_model=list[ExerciseSessionRead])
def list_exercise_sessions(
    person_id: UUID,
    session: DB,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExerciseSession]:
    person_action(session, actor, person_id, Action.VIEW)
    return list(
        session.scalars(
            select(ExerciseSession)
            .where(ExerciseSession.person_id == person_id)
            .order_by(ExerciseSession.created_at.desc(), ExerciseSession.id)
            .limit(limit)
            .offset(offset)
        )
    )


@router.get("/exercise-sessions/{session_id}", response_model=ExerciseSessionRead)
def get_exercise_session(session_id: UUID, session: DB, actor: CurrentActor) -> ExerciseSession:
    exercise = session.get(ExerciseSession, session_id)
    if exercise is None:
        raise not_found()
    person_action(session, actor, exercise.person_id, Action.VIEW)
    return exercise


def admin(actor: Actor) -> None:
    try:
        require_system_administrator(actor)
    except AuthorizationError as exc:
        raise HTTPException(403, detail={"code": "forbidden", "message": str(exc)}) from exc


def audit(
    session: Session,
    actor: Actor,
    action: str,
    target_type: str,
    target_id: UUID,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_user_account_id=actor.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details_json=details or {},
        )
    )


@router.get("/admin/pending-users")
def pending_users(session: DB, actor: CurrentActor) -> list[dict[str, object]]:
    admin(actor)
    users = session.scalars(
        select(UserAccount)
        .where(UserAccount.account_status == "pending")
        .order_by(UserAccount.created_at, UserAccount.id)
    )
    return [
        {
            "id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "email_verified": user.email_verified,
        }
        for user in users
    ]


@router.post("/admin/users/{user_id}/activate", dependencies=[Depends(require_csrf)])
def activate_user(user_id: UUID, session: DB, actor: CurrentActor) -> dict[str, str]:
    admin(actor)
    user = session.get(UserAccount, user_id)
    if user is None:
        raise not_found("User")
    user.account_status, user.is_active = "active", True
    audit(session, actor, "user.activate", "user_account", user.id)
    session.commit()
    return {"id": str(user.id), "status": user.account_status}


@router.post("/admin/users/{user_id}/disable", dependencies=[Depends(require_csrf)])
def disable_user(user_id: UUID, session: DB, actor: CurrentActor) -> dict[str, str]:
    admin(actor)
    user = session.get(UserAccount, user_id)
    if user is None or user.id == actor.user_id:
        raise HTTPException(
            409, detail={"code": "unsafe_account_change", "message": "Cannot disable this account"}
        )
    user.account_status, user.is_active = "disabled", False
    audit(session, actor, "user.disable", "user_account", user.id)
    session.commit()
    return {"id": str(user.id), "status": user.account_status}


@router.post("/admin/access-grants", status_code=201, dependencies=[Depends(require_csrf)])
def create_grant(data: AccessGrantCreate, session: DB, actor: CurrentActor) -> dict[str, str]:
    if (
        session.get(UserAccount, data.user_account_id) is None
        or session.get(Person, data.person_id) is None
        or data.role not in {"owner", "administrator", "caregiver", "viewer"}
    ):
        raise HTTPException(
            422, detail={"code": "invalid_grant", "message": "Invalid grant target or role"}
        )
    if not actor.is_system_administrator:
        person_action(session, actor, data.person_id, Action.MANAGE_ACCESS)
        if data.role not in {"caregiver", "viewer"} or data.user_account_id == actor.user_id:
            raise HTTPException(
                403,
                detail={
                    "code": "forbidden",
                    "message": "Owners may grant caregiver or viewer access to another user",
                },
            )
    existing = session.scalar(
        select(AccessGrant).where(
            AccessGrant.user_account_id == data.user_account_id,
            AccessGrant.person_id == data.person_id,
            AccessGrant.revoked_at.is_(None),
        )
    )
    if existing is not None:
        raise HTTPException(
            409,
            detail={"code": "active_grant_exists", "message": "An active grant already exists"},
        )
    grant = AccessGrant(**data.model_dump(), granted_by_user_account_id=actor.user_id)
    session.add(grant)
    session.flush()
    audit(
        session,
        actor,
        "access.grant",
        "access_grant",
        grant.id,
        {"user_id": str(data.user_account_id), "person_id": str(data.person_id), "role": data.role},
    )
    session.commit()
    return {"id": str(grant.id), "status": "active"}


@router.post("/admin/access-grants/{grant_id}/revoke", dependencies=[Depends(require_csrf)])
def revoke_grant(grant_id: UUID, session: DB, actor: CurrentActor) -> dict[str, str]:
    grant = session.get(AccessGrant, grant_id)
    if grant is None:
        raise not_found("Access grant")
    if not actor.is_system_administrator:
        person_action(session, actor, grant.person_id, Action.MANAGE_ACCESS)
        if grant.role not in {"caregiver", "viewer"}:
            raise HTTPException(
                403,
                detail={"code": "forbidden", "message": "Owners may revoke ordinary grants only"},
            )
    grant.revoked_at, grant.revoked_by_user_account_id = datetime.now(UTC), actor.user_id
    audit(session, actor, "access.revoke", "access_grant", grant.id)
    session.commit()
    return {"id": str(grant.id), "status": "revoked"}


@router.get("/admin/users/{user_id}/access-grants")
def grants_for_user(user_id: UUID, session: DB, actor: CurrentActor) -> list[dict[str, object]]:
    admin(actor)
    grants = session.scalars(
        select(AccessGrant)
        .where(AccessGrant.user_account_id == user_id)
        .order_by(AccessGrant.granted_at, AccessGrant.id)
    )
    return [
        {
            "id": str(grant.id),
            "person_id": str(grant.person_id),
            "role": grant.role,
            "revoked_at": grant.revoked_at,
        }
        for grant in grants
    ]


@router.get("/admin/persons/{person_id}/access-grants")
def grants_for_person(person_id: UUID, session: DB, actor: CurrentActor) -> list[dict[str, object]]:
    admin(actor)
    grants = session.scalars(
        select(AccessGrant)
        .where(AccessGrant.person_id == person_id)
        .order_by(AccessGrant.granted_at, AccessGrant.id)
    )
    return [
        {
            "id": str(grant.id),
            "user_account_id": str(grant.user_account_id),
            "role": grant.role,
            "revoked_at": grant.revoked_at,
        }
        for grant in grants
    ]
