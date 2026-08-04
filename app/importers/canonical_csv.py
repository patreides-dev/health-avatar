import csv
import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    HealthObservation,
    ImportBatch,
    ImportError,
    ObservationType,
    Person,
    SourceSystem,
)
from app.models.enums import ImportStatus, ValueType
from app.schemas.api import CanonicalObservationRow

EXPECTED_COLUMNS = {
    "person_external_reference",
    "observation_type",
    "observed_at",
    "value",
    "unit",
    "measurement_method",
    "reliability_classification",
    "source_record_identifier",
}


class ImportRequestError(ValueError):
    """The whole import request cannot be processed."""


def _row_error(
    session: Session,
    batch: ImportBatch,
    row_number: int,
    code: str,
    message: str,
    row: dict[str, Any],
) -> None:
    session.add(
        ImportError(
            import_batch=batch,
            source_row_number=row_number,
            error_code=code,
            error_message=message,
            raw_row_json=row,
        )
    )


def import_canonical_csv(
    session: Session,
    *,
    content: bytes,
    filename: str,
    source_system: SourceSystem,
    subject_person: Person | None = None,
) -> ImportBatch:
    """Validate and import each canonical CSV row, preserving failures and provenance."""
    digest = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(ImportBatch).where(
            ImportBatch.source_system_id == source_system.id,
            ImportBatch.file_sha256 == digest,
            ImportBatch.subject_person_id
            == (subject_person.id if subject_person is not None else None),
        )
    )
    if existing is not None:
        return existing

    batch = ImportBatch(
        source_system=source_system,
        subject_person=subject_person,
        original_filename=Path(filename).name,
        file_sha256=digest,
        status=ImportStatus.PROCESSING,
        importer_name="canonical_csv",
        importer_version="0.1.0",
    )
    session.add(batch)
    session.flush()

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        batch.status = ImportStatus.FAILED
        batch.import_completed_at = datetime.now(UTC)
        session.commit()
        raise ImportRequestError("CSV must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or set(reader.fieldnames) != EXPECTED_COLUMNS:
        batch.status = ImportStatus.FAILED
        batch.import_completed_at = datetime.now(UTC)
        session.commit()
        raise ImportRequestError("CSV header does not exactly match the canonical contract")

    for row_number, raw_row in enumerate(reader, start=2):
        batch.total_rows += 1
        row: dict[str, Any] = dict(raw_row)
        try:
            parsed = CanonicalObservationRow.model_validate(row)
        except ValidationError as exc:
            batch.rejected_rows += 1
            _row_error(session, batch, row_number, "invalid_row", str(exc), row)
            continue

        person = session.scalar(
            select(Person).where(Person.external_reference == parsed.person_external_reference)
        )
        if person is None:
            batch.rejected_rows += 1
            _row_error(session, batch, row_number, "unknown_person", "Person not found", row)
            continue
        if subject_person is not None and person.id != subject_person.id:
            batch.rejected_rows += 1
            _row_error(
                session,
                batch,
                row_number,
                "person_mismatch",
                "Row person does not match the explicitly selected subject",
                row,
            )
            continue

        observation_type = session.scalar(
            select(ObservationType).where(ObservationType.code == parsed.observation_type)
        )
        if observation_type is None:
            batch.rejected_rows += 1
            _row_error(session, batch, row_number, "unknown_observation_type", "Unknown type", row)
            continue
        if observation_type.value_type != ValueType.NUMERIC:
            batch.rejected_rows += 1
            _row_error(
                session,
                batch,
                row_number,
                "unsupported_value_type",
                "CSV value must be numeric",
                row,
            )
            continue
        if parsed.unit != observation_type.default_unit:
            batch.rejected_rows += 1
            _row_error(
                session,
                batch,
                row_number,
                "invalid_unit",
                f"Expected unit {observation_type.default_unit!r}; no conversion was performed",
                row,
            )
            continue

        duplicate = session.scalar(
            select(HealthObservation.id).where(
                HealthObservation.source_system_id == source_system.id,
                HealthObservation.source_record_identifier == parsed.source_record_identifier,
                HealthObservation.person_id == person.id,
                HealthObservation.observation_type_id == observation_type.id,
            )
        )
        if duplicate is not None:
            batch.rejected_rows += 1
            _row_error(
                session,
                batch,
                row_number,
                "duplicate_observation",
                "Observation already exists",
                row,
            )
            continue

        session.add(
            HealthObservation(
                person=person,
                observation_type=observation_type,
                observed_at=parsed.observed_at,
                numeric_value=parsed.value,
                unit=parsed.unit,
                source_system=source_system,
                import_batch=batch,
                source_record_identifier=parsed.source_record_identifier,
                source_row_number=row_number,
                raw_source_row_json=row,
                measurement_method=parsed.measurement_method,
                reliability_classification=parsed.reliability_classification,
            )
        )
        batch.accepted_rows += 1

    batch.status = (
        ImportStatus.COMPLETED_WITH_ERRORS if batch.rejected_rows else ImportStatus.COMPLETED
    )
    batch.import_completed_at = datetime.now(UTC)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(ImportBatch).where(
                ImportBatch.source_system_id == source_system.id,
                ImportBatch.file_sha256 == digest,
                ImportBatch.subject_person_id
                == (subject_person.id if subject_person is not None else None),
            )
        )
        if existing is None:
            raise
        return existing
    session.refresh(batch)
    return batch
