from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ObservationType, Person, SourceSystem
from app.models.enums import ValueType


@dataclass(frozen=True)
class ObservationTypeSeed:
    code: str
    display_name: str
    default_unit: str
    category: str


OBSERVATION_TYPES = (
    ObservationTypeSeed("body_weight", "Body weight", "lb", "body_composition"),
    ObservationTypeSeed("resting_heart_rate", "Resting heart rate", "bpm", "cardiovascular"),
    ObservationTypeSeed("sleep_duration", "Sleep duration", "hour", "sleep"),
    ObservationTypeSeed("step_count", "Step count", "count", "activity"),
    ObservationTypeSeed(
        "systolic_blood_pressure", "Systolic blood pressure", "mmHg", "cardiovascular"
    ),
    ObservationTypeSeed(
        "diastolic_blood_pressure", "Diastolic blood pressure", "mmHg", "cardiovascular"
    ),
)


def seed_development(session: Session) -> dict[str, int]:
    """Idempotently seed the controlled development catalog and synthetic demo identity."""
    created_types = 0
    for seed in OBSERVATION_TYPES:
        existing = session.scalar(select(ObservationType).where(ObservationType.code == seed.code))
        if existing is None:
            session.add(
                ObservationType(
                    code=seed.code,
                    display_name=seed.display_name,
                    description=f"Canonical {seed.display_name.lower()} observation.",
                    default_unit=seed.default_unit,
                    value_type=ValueType.NUMERIC,
                    category=seed.category,
                    active=True,
                )
            )
            created_types += 1

    person_created = 0
    if session.scalar(select(Person).where(Person.external_reference == "kevin-demo")) is None:
        session.add(
            Person(
                external_reference="kevin-demo",
                preferred_name="Kevin Demo",
                timezone="America/New_York",
            )
        )
        person_created = 1

    source_created = 0
    if session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv")) is None:
        session.add(
            SourceSystem(
                name="manual-csv",
                source_type="csv_import",
                vendor="Health Avatar",
                description="Synthetic development canonical CSV source.",
            )
        )
        source_created = 1
    session.commit()
    return {
        "observation_types_created": created_types,
        "persons_created": person_created,
        "source_systems_created": source_created,
    }
