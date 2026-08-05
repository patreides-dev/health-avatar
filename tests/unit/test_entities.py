from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import HealthObservation, ObservationType, Person, SourceSystem
from app.schemas.api import DeviceAssignmentCreate, PersonCreate
from app.services.catalog import seed_development
from app.services.entities import create_person


def test_person_creation(session: Session) -> None:
    person = create_person(
        session,
        PersonCreate(
            external_reference="person-001",
            preferred_name="Synthetic Person",
            timezone="America/New_York",
        ),
    )
    assert person.id is not None
    assert person.external_reference == "person-001"


def test_observation_type_uniqueness(session: Session) -> None:
    session.add_all(
        [
            ObservationType(
                code="same", display_name="A", description="A", value_type="numeric", category="x"
            ),
            ObservationType(
                code="same", display_name="B", description="B", value_type="numeric", category="x"
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_observation_exactly_one_typed_value(session: Session) -> None:
    person = Person(preferred_name="Synthetic", timezone="UTC")
    source = SourceSystem(name="test", source_type="test", vendor="test")
    kind = ObservationType(
        code="weight", display_name="Weight", description="Test", value_type="numeric", category="x"
    )
    session.add_all([person, source, kind])
    session.flush()
    session.add(
        HealthObservation(
            person=person,
            source_system=source,
            observation_type=kind,
            observed_at=datetime.now(UTC),
            numeric_value=Decimal("1"),
            text_value="also set",
            measurement_method="measured",
            reliability_classification="unknown",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_device_assignment_range() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError, match="assigned_until"):
        DeviceAssignmentCreate(
            person_id="00000000-0000-0000-0000-000000000001",
            device_id="00000000-0000-0000-0000-000000000002",
            assigned_from=now,
            assigned_until=now - timedelta(seconds=1),
            assignment_type="primary",
        )


def test_seed_is_idempotent(session: Session) -> None:
    first = seed_development(session)
    second = seed_development(session)
    assert first == {
        "observation_types_created": 6,
        "persons_created": 1,
        "source_systems_created": 1,
        "user_accounts_created": 5,
        "access_grants_created": 4,
    }
    assert second == {
        "observation_types_created": 0,
        "persons_created": 0,
        "source_systems_created": 0,
        "user_accounts_created": 0,
        "access_grants_created": 0,
    }
