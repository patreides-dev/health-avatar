from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.importers.canonical_csv import ImportRequestError, import_canonical_csv
from app.models import ImportBatch, Person, SourceSystem
from app.repositories.observations import count_statement, query_observations
from app.schemas.api import (
    DeviceAssignmentCreate,
    DeviceAssignmentRead,
    DeviceCreate,
    DeviceRead,
    ImportBatchRead,
    ObservationPage,
    PersonCreate,
    PersonRead,
    SourceSystemCreate,
    SourceSystemRead,
)
from app.services.entities import (
    ConflictError,
    RelatedEntityNotFoundError,
    create_device,
    create_device_assignment,
    create_person,
    create_source_system,
)

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]


def not_found(entity: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"code": "not_found", "message": f"{entity} not found"}
    )


@router.get("/persons", response_model=list[PersonRead])
def list_persons(session: DB) -> list[Person]:
    return list(session.scalars(select(Person).order_by(Person.created_at, Person.id)))


@router.post("/persons", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def post_person(data: PersonCreate, session: DB) -> Person:
    try:
        return create_person(session, data)
    except ConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc


@router.get("/persons/{person_id}", response_model=PersonRead)
def get_person(person_id: UUID, session: DB) -> Person:
    person = session.get(Person, person_id)
    if person is None:
        raise not_found("Person")
    return person


@router.post(
    "/source-systems", response_model=SourceSystemRead, status_code=status.HTTP_201_CREATED
)
def post_source_system(data: SourceSystemCreate, session: DB) -> SourceSystem:
    try:
        return create_source_system(session, data)
    except ConflictError as exc:
        raise HTTPException(409, detail={"code": "conflict", "message": str(exc)}) from exc


@router.post("/devices", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def post_device(data: DeviceCreate, session: DB) -> object:
    try:
        return create_device(session, data)
    except RelatedEntityNotFoundError as exc:
        raise not_found(str(exc).replace(" not found", "")) from exc


@router.post(
    "/device-assignments",
    response_model=DeviceAssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
def post_device_assignment(data: DeviceAssignmentCreate, session: DB) -> object:
    try:
        return create_device_assignment(session, data)
    except RelatedEntityNotFoundError as exc:
        raise not_found(str(exc).replace(" not found", "")) from exc


@router.post("/imports/csv", response_model=ImportBatchRead)
def post_csv_import(
    session: DB,
    file: Annotated[UploadFile, File()],
    source_system_id: Annotated[UUID, Form()],
    person_external_reference: Annotated[str | None, Form()] = None,
) -> ImportBatch:
    source = session.get(SourceSystem, source_system_id)
    if source is None:
        raise not_found("Source system")
    person = None
    if person_external_reference:
        person = session.scalar(
            select(Person).where(Person.external_reference == person_external_reference)
        )
        if person is None:
            raise not_found("Person")
    try:
        return import_canonical_csv(
            session,
            content=file.file.read(),
            filename=file.filename or "upload.csv",
            source_system=source,
            subject_person=person,
        )
    except ImportRequestError as exc:
        raise HTTPException(422, detail={"code": "invalid_import", "message": str(exc)}) from exc


@router.get("/imports/{import_batch_id}", response_model=ImportBatchRead)
def get_import(import_batch_id: UUID, session: DB) -> ImportBatch:
    batch = session.get(ImportBatch, import_batch_id)
    if batch is None:
        raise not_found("Import batch")
    return batch


@router.get("/persons/{person_id}/observations", response_model=ObservationPage)
def get_observations(
    person_id: UUID,
    session: DB,
    observation_type: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    source_system_id: UUID | None = None,
    device_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ObservationPage:
    if session.get(Person, person_id) is None:
        raise not_found("Person")
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
    items = list(session.scalars(statement.limit(limit).offset(offset)))
    return ObservationPage(items=items, total=total, limit=limit, offset=offset)
