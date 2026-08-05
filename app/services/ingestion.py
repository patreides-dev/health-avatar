import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.ingestion.canonical_csv import registry_adapter
from app.ingestion.contracts import AdapterRequest
from app.ingestion.registry import AdapterNotFoundError, AdapterRegistry
from app.models import (
    AccessGrant,
    CandidateRecord,
    HealthObservation,
    ImportBatch,
    ObservationType,
    Person,
    ProcessingRun,
    SourceArtifact,
    SourceSystem,
    ValidationIssue,
)
from app.models import ImportError as ImportErrorRecord
from app.models.enums import CandidateStatus, ImportStatus, ProcessingStatus
from app.services.auth import Actor
from app.services.authorization import Action, authorize
from app.services.promotion import PromotionError, promote_candidate
from app.services.storage import ArtifactStorage

SUPPORTED_CSV_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
registry = AdapterRegistry([registry_adapter])


class IngestionError(ValueError):
    pass


def _scope(digest: str, source_system_id: UUID | None, person_id: UUID | None) -> str:
    value = f"{digest}|{source_system_id or 'none'}|{person_id or 'unresolved'}"
    return hashlib.sha256(value.encode()).hexdigest()


def accept_artifact(
    session: Session,
    *,
    content: bytes,
    filename: str | None,
    media_type: str,
    artifact_kind: str,
    sensitivity: str,
    person: Person | None,
    source_system: SourceSystem | None,
    actor: Actor,
    storage: ArtifactStorage,
    settings: Settings,
) -> SourceArtifact:
    if len(content) > settings.max_artifact_bytes:
        raise IngestionError("Artifact exceeds configured size limit")
    if artifact_kind == "file" and media_type not in SUPPORTED_CSV_TYPES:
        raise IngestionError("Unsupported content type")
    if artifact_kind == "file" and (not filename or Path(filename).suffix.lower() != ".csv"):
        raise IngestionError("Canonical CSV artifacts require a .csv filename")
    if person is not None:
        authorize(session, actor, person.id, Action.SUBMIT)
    digest = hashlib.sha256(content).hexdigest()
    scope = _scope(
        digest, source_system.id if source_system else None, person.id if person else None
    )
    existing = session.scalar(
        select(SourceArtifact).where(SourceArtifact.idempotency_scope == scope)
    )
    if existing is not None:
        return existing
    artifact = SourceArtifact(
        subject_person_id=person.id if person else None,
        source_system_id=source_system.id if source_system else None,
        submitted_by_user_account_id=actor.user_id,
        artifact_kind=artifact_kind,
        media_type=media_type,
        original_filename=Path(filename).name if filename else None,
        file_sha256=digest,
        content_length=len(content),
        storage_backend=storage.backend_name,
        storage_key=None,
        idempotency_scope=scope,
        processing_status="pending",
        sensitivity_classification=sensitivity,
        metadata_json={},
    )
    session.add(artifact)
    session.flush()
    key = f"sha256/{digest[:2]}/{digest[2:4]}/{artifact.id}"
    storage.put(key, content)
    artifact.storage_key = key
    session.commit()
    session.refresh(artifact)
    return artifact


def process_artifact(
    session: Session,
    *,
    artifact: SourceArtifact,
    content: bytes,
    actor: Actor,
    explicit_adapter: str | None = None,
) -> ProcessingRun:
    if artifact.subject_person_id is not None:
        authorize(session, actor, artifact.subject_person_id, Action.SUBMIT)
    try:
        adapter = registry.select(
            artifact_kind=artifact.artifact_kind,
            media_type=artifact.media_type,
            filename=artifact.original_filename,
            explicit_name=explicit_adapter,
        )
    except AdapterNotFoundError as exc:
        raise IngestionError(str(exc)) from exc
    existing = session.scalar(
        select(ProcessingRun).where(
            ProcessingRun.source_artifact_id == artifact.id,
            ProcessingRun.adapter_name == adapter.name,
            ProcessingRun.schema_version == adapter.schema_version,
        )
    )
    if existing is not None:
        return existing
    run = ProcessingRun(
        source_artifact_id=artifact.id,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        schema_version=adapter.schema_version,
        requested_by_user_account_id=actor.user_id,
        status=ProcessingStatus.PROCESSING,
        configuration_json={},
    )
    session.add(run)
    session.flush()
    now = datetime.now(UTC)
    visible_people = (
        select(Person.external_reference, Person.id)
        .join(AccessGrant, AccessGrant.person_id == Person.id)
        .where(
            AccessGrant.user_account_id == actor.user_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
        )
    )
    people = {
        reference: person_id
        for reference, person_id in session.execute(visible_people)
        if reference is not None
    }
    types = {
        code: (type_id, unit, value_type)
        for code, type_id, unit, value_type in session.execute(
            select(
                ObservationType.code,
                ObservationType.id,
                ObservationType.default_unit,
                ObservationType.value_type,
            )
        )
    }
    try:
        source_system = (
            session.get(SourceSystem, artifact.source_system_id)
            if artifact.source_system_id
            else None
        )
        result = adapter.inspect(
            AdapterRequest(
                content=content,
                artifact_kind=artifact.artifact_kind,
                media_type=artifact.media_type,
                filename=artifact.original_filename,
                source_system_name=source_system.name if source_system else None,
                subject_person_id=artifact.subject_person_id,
                people_by_reference=people,
                observation_types=types,
            )
        )
    except ValueError as exc:
        run.status = ProcessingStatus.FAILED
        run.error_summary = str(exc)
        run.completed_at = datetime.now(UTC)
        artifact.processing_status = "failed"
        session.commit()
        raise IngestionError(str(exc)) from exc
    records: list[CandidateRecord] = []
    for draft in result.candidate_records:
        record = CandidateRecord(
            processing_run_id=run.id,
            subject_person_id=draft.subject_person_id,
            candidate_type=draft.candidate_type,
            source_locator=draft.source_locator,
            status=draft.status,
            confidence=draft.confidence,
            raw_candidate_json=draft.raw,
            normalized_candidate_json=draft.normalized,
        )
        session.add(record)
        records.append(record)
    session.flush()
    for issue in result.validation_issues:
        session.add(
            ValidationIssue(
                processing_run_id=run.id,
                candidate_record_id=records[issue.candidate_index].id
                if issue.candidate_index is not None
                else None,
                field_name=issue.field_name,
                severity=issue.severity,
                issue_code=issue.issue_code,
                message=issue.message,
                source_locator=issue.source_locator,
                details_json=issue.details,
            )
        )
    promoted = 0
    for record in records:
        if record.status == CandidateStatus.APPROVED:
            try:
                with session.begin_nested():
                    promote_candidate(session, candidate=record, actor=actor, automatic=True)
                promoted += 1
            except PromotionError as exc:
                record.status = CandidateStatus.PROMOTION_FAILED
                session.add(
                    ValidationIssue(
                        processing_run_id=run.id,
                        candidate_record_id=record.id,
                        severity="error",
                        issue_code="promotion_failed",
                        message=str(exc),
                        source_locator=record.source_locator,
                        details_json={},
                    )
                )
    run.candidate_count = len(records)
    run.accepted_count = promoted
    run.rejected_count = result.processing_summary.invalid + sum(
        record.status == CandidateStatus.PROMOTION_FAILED for record in records
    )
    run.review_required_count = result.processing_summary.review_required
    run.status = (
        ProcessingStatus.COMPLETED_WITH_ERRORS if run.rejected_count else ProcessingStatus.COMPLETED
    )
    run.completed_at = datetime.now(UTC)
    artifact.processing_status = run.status
    session.commit()
    session.refresh(run)
    return run


def ingest_csv(
    session: Session,
    *,
    content: bytes,
    filename: str,
    source_system: SourceSystem,
    subject_person: Person,
    actor: Actor,
    storage: ArtifactStorage,
    settings: Settings,
) -> tuple[SourceArtifact, ProcessingRun, ImportBatch]:
    artifact = accept_artifact(
        session,
        content=content,
        filename=filename,
        media_type="text/csv",
        artifact_kind="file",
        sensitivity="general_health",
        person=subject_person,
        source_system=source_system,
        actor=actor,
        storage=storage,
        settings=settings,
    )
    run = process_artifact(
        session, artifact=artifact, content=content, actor=actor, explicit_adapter="canonical_csv"
    )
    batch = session.scalar(select(ImportBatch).where(ImportBatch.processing_run_id == run.id))
    if batch is None:
        batch = ImportBatch(
            source_system_id=source_system.id,
            source_artifact_id=artifact.id,
            processing_run_id=run.id,
            subject_person_id=subject_person.id,
            imported_by_user_account_id=actor.user_id,
            original_filename=artifact.original_filename or "upload.csv",
            file_sha256=artifact.file_sha256 or "",
            status=(
                ImportStatus.FAILED
                if run.status == ProcessingStatus.FAILED
                else ImportStatus.COMPLETED_WITH_ERRORS
                if run.rejected_count
                else ImportStatus.COMPLETED
            ),
            total_rows=run.candidate_count,
            accepted_rows=run.accepted_count,
            rejected_rows=run.rejected_count,
            importer_name=run.adapter_name,
            importer_version=run.adapter_version,
            import_completed_at=run.completed_at,
        )
        session.add(batch)
        session.flush()
        candidates = {
            candidate.id: candidate
            for candidate in session.scalars(
                select(CandidateRecord).where(CandidateRecord.processing_run_id == run.id)
            )
        }
        for issue in session.scalars(
            select(ValidationIssue).where(
                ValidationIssue.processing_run_id == run.id,
                ValidationIssue.severity == "error",
            )
        ):
            candidate = (
                candidates.get(issue.candidate_record_id)
                if issue.candidate_record_id is not None
                else None
            )
            locator = issue.source_locator or (candidate.source_locator if candidate else "")
            row_number = int(locator.removeprefix("row:")) if locator.startswith("row:") else 0
            session.add(
                ImportErrorRecord(
                    import_batch_id=batch.id,
                    source_row_number=row_number,
                    error_code=issue.issue_code,
                    error_message=issue.message,
                    raw_row_json=candidate.raw_candidate_json if candidate else {},
                )
            )
        for observation in session.scalars(
            select(HealthObservation).where(HealthObservation.processing_run_id == run.id)
        ):
            observation.import_batch_id = batch.id
        session.commit()
        session.refresh(batch)
    return artifact, run, batch
