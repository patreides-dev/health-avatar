from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.importers.canonical_csv import EXPECTED_COLUMNS, import_canonical_csv
from app.models import HealthObservation, ImportError, Person, SourceSystem

HEADER = ",".join(EXPECTED_COLUMNS)
HEADER = (
    "person_external_reference,observation_type,observed_at,value,unit,measurement_method,"
    "reliability_classification,source_record_identifier"
)


def csv_bytes(*rows: str) -> bytes:
    return (HEADER + "\n" + "\n".join(rows) + "\n").encode()


def context(session: Session) -> tuple[Person, SourceSystem]:
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    source = session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv"))
    assert person is not None and source is not None
    return person, source


def test_successful_csv_import(seeded_session: Session) -> None:
    person, source = context(seeded_session)
    batch = import_canonical_csv(
        seeded_session,
        content=csv_bytes(
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,weight-test"
        ),
        filename="safe.csv",
        source_system=source,
        subject_person=person,
    )
    assert (batch.status, batch.total_rows, batch.accepted_rows, batch.rejected_rows) == (
        "completed",
        1,
        1,
        0,
    )
    observation = seeded_session.scalar(select(HealthObservation))
    assert observation is not None
    assert observation.source_row_number == 2
    assert observation.import_batch_id == batch.id
    assert observation.raw_source_row_json is not None
    assert observation.raw_source_row_json["value"] == "238.4"


def test_partially_rejected_import_and_statistics(seeded_session: Session) -> None:
    person, source = context(seeded_session)
    batch = import_canonical_csv(
        seeded_session,
        content=csv_bytes(
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,ok-1",
            "missing,body_weight,2026-08-01T07:15:00-04:00,1,lb,measured,unknown,bad-1",
            "kevin-demo,unknown_type,2026-08-01T07:15:00-04:00,1,lb,measured,unknown,bad-2",
            "kevin-demo,body_weight,2026-08-01T07:15:00-04:00,1,kg,measured,unknown,bad-3",
        ),
        filename="partial.csv",
        source_system=source,
    )
    assert (batch.status, batch.total_rows, batch.accepted_rows, batch.rejected_rows) == (
        "completed_with_errors",
        4,
        1,
        3,
    )
    codes = set(seeded_session.scalars(select(ImportError.error_code)))
    assert codes == {"unknown_person", "unknown_observation_type", "invalid_unit"}


def test_duplicate_file_is_idempotent(seeded_session: Session) -> None:
    person, source = context(seeded_session)
    content = csv_bytes(
        "kevin-demo,step_count,2026-08-01T12:00:00-04:00,100,count,measured,consumer_device,steps-1"
    )
    first = import_canonical_csv(
        seeded_session,
        content=content,
        filename="first.csv",
        source_system=source,
        subject_person=person,
    )
    second = import_canonical_csv(
        seeded_session,
        content=content,
        filename="renamed.csv",
        source_system=source,
        subject_person=person,
    )
    assert second.id == first.id
    assert seeded_session.scalar(select(func.count()).select_from(HealthObservation)) == 1
