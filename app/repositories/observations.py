from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models import HealthObservation, ObservationType


def query_observations(
    session: Session,
    *,
    person_id: UUID,
    observation_type: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    source_system_id: UUID | None = None,
    device_id: UUID | None = None,
) -> Select[tuple[HealthObservation]]:
    statement = select(HealthObservation).where(HealthObservation.person_id == person_id)
    if observation_type:
        statement = statement.join(ObservationType).where(ObservationType.code == observation_type)
    if observed_from:
        statement = statement.where(HealthObservation.observed_at >= observed_from)
    if observed_to:
        statement = statement.where(HealthObservation.observed_at <= observed_to)
    if source_system_id:
        statement = statement.where(HealthObservation.source_system_id == source_system_id)
    if device_id:
        statement = statement.where(HealthObservation.device_id == device_id)
    return statement.options(selectinload(HealthObservation.observation_type)).order_by(
        HealthObservation.observed_at.desc(), HealthObservation.id
    )


def count_statement(statement: Select[tuple[HealthObservation]]) -> Select[tuple[int]]:
    return select(func.count()).select_from(statement.order_by(None).subquery())
