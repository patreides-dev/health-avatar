# ruff: noqa: E501
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.ingestion.canonical_csv import EXPECTED_COLUMNS
from app.ingestion.registry import AdapterNotFoundError, AdapterRegistry
from app.models import (
    CandidateRecord,
    HealthObservation,
    ImportBatch,
    ImportError,
    Person,
    ProcessingRun,
    SourceArtifact,
    SourceSystem,
    UserAccount,
    ValidationIssue,
)
from app.services.auth import Actor
from app.services.ingestion import ingest_csv, registry
from app.services.storage import LocalArtifactStorage

HEADER = "person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier"


def csv_bytes(*rows: str) -> bytes:
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


def context(session: Session) -> tuple[Person, SourceSystem, Actor]:
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    source = session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv"))
    owner = session.scalar(select(UserAccount).where(UserAccount.provider_subject == "dev-owner"))
    assert person is not None and source is not None and owner is not None
    return person, source, Actor(owner.id)


def run(
    session: Session, tmp_path: Path, content: bytes
) -> tuple[SourceArtifact, ProcessingRun, ImportBatch]:
    person, source, actor = context(session)
    settings = Settings(app_env="testing", artifact_storage_path=tmp_path / "artifacts")
    return ingest_csv(
        session,
        content=content,
        filename="safe.csv",
        source_system=source,
        subject_person=person,
        actor=actor,
        storage=LocalArtifactStorage(settings.artifact_storage_path),
        settings=settings,
    )


def test_registry_selects_typed_csv_adapter() -> None:
    adapter = registry.select(artifact_kind="file", media_type="text/csv", filename="safe.csv")
    assert (adapter.name, adapter.version, adapter.schema_version) == (
        "canonical_csv",
        "0.2.0",
        "1",
    )
    assert EXPECTED_COLUMNS
    try:
        AdapterRegistry([]).select(artifact_kind="image", media_type="image/png", filename="x.png")
    except AdapterNotFoundError as exc:
        assert "registered adapter" in str(exc)
    else:
        raise AssertionError("unknown adapter should fail")


def test_successful_csv_uses_staged_pipeline(seeded_session: Session, tmp_path: Path) -> None:
    artifact, processing, batch = run(
        seeded_session,
        tmp_path,
        csv_bytes(
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,weight-test"
        ),
    )
    assert (
        processing.status,
        processing.candidate_count,
        processing.accepted_count,
        processing.rejected_count,
    ) == ("completed", 1, 1, 0)
    candidate = seeded_session.scalar(select(CandidateRecord))
    observation = seeded_session.scalar(select(HealthObservation))
    assert candidate is not None and observation is not None
    assert candidate.source_locator == "row:2" and candidate.status == "promoted"
    assert observation.candidate_record_id == candidate.id
    assert observation.source_artifact_id == artifact.id
    assert observation.processing_run_id == processing.id
    assert observation.import_batch_id == batch.id
    assert observation.raw_source_row_json["value"] == "238.4"


def test_partial_failure_retains_candidates_and_issues(
    seeded_session: Session, tmp_path: Path
) -> None:
    _, processing, batch = run(
        seeded_session,
        tmp_path,
        csv_bytes(
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,ok-1",
            "missing,body_weight,2026-08-01T07:15:00-04:00,1,lb,measured,unknown,bad-1",
            "kevin-demo,unknown_type,2026-08-01T07:15:00-04:00,1,lb,measured,unknown,bad-2",
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,1,kg,measured,unknown,bad-3",
        ),
    )
    assert (processing.status, batch.total_rows, batch.accepted_rows, batch.rejected_rows) == (
        "completed_with_errors",
        4,
        1,
        3,
    )
    assert set(seeded_session.scalars(select(ValidationIssue.issue_code))) == {
        "unknown_person",
        "unknown_observation_type",
        "invalid_unit",
    }
    assert seeded_session.scalar(select(func.count()).select_from(CandidateRecord)) == 4
    assert seeded_session.scalar(select(func.count()).select_from(HealthObservation)) == 1
    errors = list(
        seeded_session.scalars(select(ImportError).order_by(ImportError.source_row_number))
    )
    assert [error.source_row_number for error in errors] == [3, 4, 5]
    assert errors[0].raw_row_json["person_external_reference"] == "missing"


def test_duplicate_operation_returns_prior_artifact_run_and_batch(
    seeded_session: Session, tmp_path: Path
) -> None:
    content = csv_bytes(
        "kevin-demo,step_count,2026-08-01T12:00:00-04:00,100,count,measured,consumer_device,steps-1"
    )
    first = run(seeded_session, tmp_path, content)
    second = run(seeded_session, tmp_path, content)
    assert [item.id for item in first] == [item.id for item in second]
    assert seeded_session.scalar(select(func.count()).select_from(HealthObservation)) == 1


def test_cross_artifact_duplicate_failure_keeps_coherent_state(
    seeded_session: Session, tmp_path: Path
) -> None:
    content = csv_bytes(
        "kevin-demo,step_count,2026-08-01T12:00:00-04:00,100,count,measured,consumer_device,duplicate-source-id"
    )
    run(seeded_session, tmp_path, content)
    _, second_run, second_batch = run(seeded_session, tmp_path, content + b"\n")
    assert second_run.status == "completed_with_errors"
    assert (second_run.candidate_count, second_run.accepted_count, second_run.rejected_count) == (
        1,
        0,
        1,
    )
    assert (second_batch.total_rows, second_batch.accepted_rows, second_batch.rejected_rows) == (
        1,
        0,
        1,
    )
    candidate = seeded_session.scalar(
        select(CandidateRecord).where(CandidateRecord.processing_run_id == second_run.id)
    )
    assert candidate is not None and candidate.status == "promotion_failed"
    assert seeded_session.scalar(select(func.count()).select_from(HealthObservation)) == 1


def test_same_bytes_are_scoped_to_person(seeded_session: Session, tmp_path: Path) -> None:
    other = Person(external_reference="other", preferred_name="Other", timezone="UTC")
    seeded_session.add(other)
    seeded_session.flush()
    owner = seeded_session.scalar(
        select(UserAccount).where(UserAccount.provider_subject == "dev-owner")
    )
    from app.models import AccessGrant

    seeded_session.add(AccessGrant(user_account_id=owner.id, person_id=other.id, role="owner"))
    seeded_session.commit()
    person, source, actor = context(seeded_session)
    settings = Settings(app_env="testing", artifact_storage_path=tmp_path / "artifacts")
    storage = LocalArtifactStorage(settings.artifact_storage_path)
    content = csv_bytes(
        "kevin-demo,step_count,2026-08-01T12:00:00-04:00,100,count,measured,consumer_device,steps-shared"
    )
    first, _, _ = ingest_csv(
        seeded_session,
        content=content,
        filename="a.csv",
        source_system=source,
        subject_person=person,
        actor=actor,
        storage=storage,
        settings=settings,
    )
    second, run2, _ = ingest_csv(
        seeded_session,
        content=content,
        filename="a.csv",
        source_system=source,
        subject_person=other,
        actor=actor,
        storage=storage,
        settings=settings,
    )
    assert first.id != second.id
    assert run2.rejected_count == 1
