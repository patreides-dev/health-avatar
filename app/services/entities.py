from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Device, Person, PersonDeviceAssignment, SourceSystem
from app.schemas.api import DeviceAssignmentCreate, DeviceCreate, PersonCreate, SourceSystemCreate


class ConflictError(ValueError):
    """A requested entity conflicts with an existing database record."""


class RelatedEntityNotFoundError(ValueError):
    """A referenced entity does not exist."""


def _commit(session: Session, entity: object) -> None:
    session.add(entity)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("A record with the same unique identity already exists") from exc
    session.refresh(entity)


def create_person(session: Session, data: PersonCreate) -> Person:
    person = Person(**data.model_dump(mode="python"))
    _commit(session, person)
    return person


def create_source_system(session: Session, data: SourceSystemCreate) -> SourceSystem:
    source = SourceSystem(**data.model_dump())
    _commit(session, source)
    return source


def create_device(session: Session, data: DeviceCreate) -> Device:
    if data.source_system_id and session.get(SourceSystem, data.source_system_id) is None:
        raise RelatedEntityNotFoundError("Source system not found")
    device = Device(**data.model_dump())
    _commit(session, device)
    return device


def create_device_assignment(
    session: Session, data: DeviceAssignmentCreate
) -> PersonDeviceAssignment:
    if session.get(Person, data.person_id) is None:
        raise RelatedEntityNotFoundError("Person not found")
    if session.get(Device, data.device_id) is None:
        raise RelatedEntityNotFoundError("Device not found")
    assignment = PersonDeviceAssignment(**data.model_dump())
    _commit(session, assignment)
    return assignment
