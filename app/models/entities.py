from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AccessRole,
    ImportStatus,
    PersonStatus,
    ValueType,
)

JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


class Person(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "persons"

    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True)
    preferred_name: Mapped[str] = mapped_column(String(255))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    status: Mapped[str] = mapped_column(String(32), default=PersonStatus.ACTIVE)

    observations: Mapped[list["HealthObservation"]] = relationship(back_populates="person")
    device_assignments: Mapped[list["PersonDeviceAssignment"]] = relationship(
        back_populates="person"
    )


class UserAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_accounts"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    access_grants: Mapped[list["AccessGrant"]] = relationship(back_populates="user_account")


class AccessGrant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="valid_period"),
    )

    user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    role: Mapped[str] = mapped_column(String(32), default=AccessRole.VIEWER)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_account: Mapped[UserAccount] = relationship(back_populates="access_grants")
    person: Mapped[Person] = relationship()


class Household(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "households"

    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    memberships: Mapped[list["HouseholdMembership"]] = relationship(back_populates="household")


class HouseholdMembership(Base):
    __tablename__ = "household_memberships"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= joined_at", name="valid_period"),
    )

    household_id: Mapped[UUID] = mapped_column(ForeignKey("households.id"), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"), primary_key=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    relationship_label: Mapped[str | None] = mapped_column(String(100))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    household: Mapped[Household] = relationship(back_populates="memberships")
    person: Mapped[Person] = relationship()


class SourceSystem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "source_systems"

    name: Mapped[str] = mapped_column(String(255), unique=True)
    source_type: Mapped[str] = mapped_column(String(100))
    vendor: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "devices"

    source_system_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_systems.id"))
    manufacturer: Mapped[str] = mapped_column(String(255))
    model: Mapped[str] = mapped_column(String(255))
    device_type: Mapped[str] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(255))
    external_device_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_system: Mapped[SourceSystem | None] = relationship()
    assignments: Mapped[list["PersonDeviceAssignment"]] = relationship(back_populates="device")


class PersonDeviceAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "person_device_assignments"
    __table_args__ = (
        CheckConstraint(
            "assigned_until IS NULL OR assigned_until > assigned_from", name="valid_period"
        ),
    )

    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"))
    assigned_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    assigned_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assignment_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    person: Mapped[Person] = relationship(back_populates="device_assignments")
    device: Mapped[Device] = relationship(back_populates="assignments")


class ImportBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        UniqueConstraint(
            "source_system_id", "file_sha256", "subject_person_id", name="uq_import_batch_file"
        ),
        CheckConstraint("total_rows >= 0", name="nonnegative_total"),
        CheckConstraint("accepted_rows >= 0", name="nonnegative_accepted"),
        CheckConstraint("rejected_rows >= 0", name="nonnegative_rejected"),
    )

    source_system_id: Mapped[UUID] = mapped_column(ForeignKey("source_systems.id"))
    subject_person_id: Mapped[UUID | None] = mapped_column(ForeignKey("persons.id"))
    imported_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    original_filename: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64))
    import_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    import_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default=ImportStatus.PENDING)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    accepted_rows: Mapped[int] = mapped_column(Integer, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0)
    importer_name: Mapped[str] = mapped_column(String(255))
    importer_version: Mapped[str] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[SourceSystem] = relationship()
    subject_person: Mapped[Person | None] = relationship(foreign_keys=[subject_person_id])
    errors: Mapped[list["ImportError"]] = relationship(back_populates="import_batch")


class ObservationType(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "observation_types"

    code: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    default_unit: Mapped[str | None] = mapped_column(String(50))
    value_type: Mapped[str] = mapped_column(String(32), default=ValueType.NUMERIC)
    category: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class HealthObservation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "health_observations"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN numeric_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN text_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN boolean_value IS NULL THEN 0 ELSE 1 END) = 1",
            name="exactly_one_typed_value",
        ),
        CheckConstraint(
            "observed_until IS NULL OR observed_until >= observed_at", name="valid_period"
        ),
        UniqueConstraint(
            "source_system_id",
            "source_record_identifier",
            "person_id",
            "observation_type_id",
            name="uq_observation_source_record",
        ),
    )

    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"), index=True)
    observation_type_id: Mapped[UUID] = mapped_column(ForeignKey("observation_types.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    text_value: Mapped[str | None] = mapped_column(Text)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean)
    unit: Mapped[str | None] = mapped_column(String(50))
    source_system_id: Mapped[UUID] = mapped_column(ForeignKey("source_systems.id"))
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"))
    import_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("import_batches.id"))
    source_record_identifier: Mapped[str | None] = mapped_column(String(500))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    raw_source_row_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    measurement_method: Mapped[str] = mapped_column(String(32))
    reliability_classification: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    person: Mapped[Person] = relationship(back_populates="observations")
    observation_type: Mapped[ObservationType] = relationship()
    source_system: Mapped[SourceSystem] = relationship()
    device: Mapped[Device | None] = relationship()
    import_batch: Mapped[ImportBatch | None] = relationship()


class ImportError(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "import_errors"

    import_batch_id: Mapped[UUID] = mapped_column(ForeignKey("import_batches.id"))
    source_row_number: Mapped[int] = mapped_column(Integer)
    error_code: Mapped[str] = mapped_column(String(100))
    error_message: Mapped[str] = mapped_column(Text)
    raw_row_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    import_batch: Mapped[ImportBatch] = relationship(back_populates="errors")
