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
    Index,
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
    AccountStatus,
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
    __table_args__ = (
        UniqueConstraint("auth_provider", "provider_subject", name="uq_user_provider_subject"),
    )

    auth_provider: Mapped[str | None] = mapped_column(String(50))
    provider_subject: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(255))
    profile_image_url: Mapped[str | None] = mapped_column(String(1000))
    account_status: Mapped[str] = mapped_column(String(32), default=AccountStatus.PENDING)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_system_administrator: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_grants: Mapped[list["AccessGrant"]] = relationship(
        back_populates="user_account", foreign_keys="AccessGrant.user_account_id"
    )


class AccessGrant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        CheckConstraint("revoked_at IS NULL OR revoked_at >= granted_at", name="valid_period"),
        CheckConstraint("expires_at IS NULL OR expires_at >= granted_at", name="valid_expiry"),
        Index(
            "ix_access_grants_user_person_active",
            "user_account_id",
            "person_id",
            "revoked_at",
            "expires_at",
        ),
    )

    user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    role: Mapped[str] = mapped_column(String(32), default=AccessRole.VIEWER)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    revoked_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    user_account: Mapped[UserAccount] = relationship(
        back_populates="access_grants", foreign_keys=[user_account_id]
    )
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
        CheckConstraint("total_rows >= 0", name="nonnegative_total"),
        CheckConstraint("accepted_rows >= 0", name="nonnegative_accepted"),
        CheckConstraint("rejected_rows >= 0", name="nonnegative_rejected"),
        Index(
            "ix_import_batches_file_scope",
            "source_system_id",
            "file_sha256",
            "subject_person_id",
        ),
    )

    source_system_id: Mapped[UUID] = mapped_column(ForeignKey("source_systems.id"))
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    processing_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_runs.id"), unique=True
    )
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
        Index(
            "ix_health_observations_person_type_time",
            "person_id",
            "observation_type_id",
            "observed_at",
        ),
        Index(
            "ix_health_observations_provenance",
            "source_artifact_id",
            "processing_run_id",
            "candidate_record_id",
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
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    processing_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_runs.id"))
    candidate_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("candidate_records.id"), unique=True
    )
    created_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    approved_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    adapter_name: Mapped[str | None] = mapped_column(String(255))
    adapter_version: Mapped[str | None] = mapped_column(String(50))
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


class AppSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "app_sessions"

    user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_account: Mapped[UserAccount] = relationship()


class SourceArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        Index("ix_source_artifacts_person_received", "subject_person_id", "received_at"),
    )

    subject_person_id: Mapped[UUID | None] = mapped_column(ForeignKey("persons.id"))
    source_system_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_systems.id"))
    submitted_by_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    parent_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    artifact_kind: Mapped[str] = mapped_column(String(100))
    media_type: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str | None] = mapped_column(String(500))
    original_external_reference: Mapped[str | None] = mapped_column(String(1000))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    content_length: Mapped[int | None] = mapped_column(Integer)
    storage_backend: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str | None] = mapped_column(String(500), unique=True)
    idempotency_scope: Mapped[str] = mapped_column(String(64), unique=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processing_status: Mapped[str] = mapped_column(String(50), default="pending")
    sensitivity_classification: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict)


class ProcessingRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_artifact_id", "adapter_name", "schema_version", name="uq_processing_scope"
        ),
        Index("ix_processing_runs_artifact_status", "source_artifact_id", "status"),
    )

    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("source_artifacts.id"))
    adapter_name: Mapped[str] = mapped_column(String(255))
    adapter_version: Mapped[str] = mapped_column(String(50))
    schema_version: Mapped[str] = mapped_column(String(50))
    requested_by_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    review_required_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CandidateRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "candidate_records"
    __table_args__ = (Index("ix_candidate_records_run_status", "processing_run_id", "status"),)

    processing_run_id: Mapped[UUID] = mapped_column(ForeignKey("processing_runs.id"))
    subject_person_id: Mapped[UUID | None] = mapped_column(ForeignKey("persons.id"))
    candidate_type: Mapped[str] = mapped_column(String(100))
    source_locator: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    raw_candidate_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT)
    normalized_candidate_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    approved_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_user_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_accounts.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class ValidationIssue(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "validation_issues"

    processing_run_id: Mapped[UUID] = mapped_column(ForeignKey("processing_runs.id"), index=True)
    candidate_record_id: Mapped[UUID | None] = mapped_column(ForeignKey("candidate_records.id"))
    field_name: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(20))
    issue_code: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    source_locator: Mapped[str | None] = mapped_column(String(500))
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    actor_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[UUID] = mapped_column(index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIIntakeRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_intake_requests"
    __table_args__ = (
        Index("ix_ai_intake_person_created", "person_id", "created_at"),
        Index("ix_ai_intake_status", "status"),
    )

    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    submitted_by_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("source_artifacts.id"))
    processing_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_runs.id"))
    input_modality: Mapped[str] = mapped_column(String(50))
    intake_purpose: Mapped[str] = mapped_column(String(100))
    user_context_text: Mapped[str | None] = mapped_column(Text)
    provider_name: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(255))
    prompt_template_name: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(50))
    output_schema_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    raw_model_response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    submission_summary: Mapped[str | None] = mapped_column(Text)
    unresolved_content: Mapped[list[Any]] = mapped_column(JSON_VARIANT, default=list)
    overall_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIProcessingConsent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_processing_consents"
    __table_args__ = (Index("ix_ai_consent_user_time", "user_account_id", "consented_at"),)

    ai_intake_request_id: Mapped[UUID] = mapped_column(ForeignKey("ai_intake_requests.id"))
    user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("source_artifacts.id"))
    provider_name: Mapped[str] = mapped_column(String(100))
    model_name: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(100))
    policy_version: Mapped[str] = mapped_column(String(50))
    consented_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProposedHealthFactGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proposed_health_fact_groups"
    __table_args__ = (
        UniqueConstraint("ai_intake_request_id", "group_identifier", name="uq_intake_fact_group"),
        Index("ix_fact_groups_run_type", "processing_run_id", "group_type"),
    )

    ai_intake_request_id: Mapped[UUID] = mapped_column(ForeignKey("ai_intake_requests.id"))
    processing_run_id: Mapped[UUID] = mapped_column(ForeignKey("processing_runs.id"))
    subject_person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    group_identifier: Mapped[str] = mapped_column(String(255))
    group_type: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="awaiting_review")


class ProposedHealthFact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proposed_health_facts"
    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "(CASE WHEN numeric_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN text_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN boolean_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN date_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN datetime_value IS NULL THEN 0 ELSE 1 END) <= 1",
            name="at_most_one_typed_value",
        ),
        Index("ix_proposed_facts_run_status", "processing_run_id", "canonical_status"),
        Index("ix_proposed_facts_group", "fact_group_id"),
    )

    processing_run_id: Mapped[UUID] = mapped_column(ForeignKey("processing_runs.id"))
    candidate_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_records.id"), unique=True
    )
    fact_group_id: Mapped[UUID | None] = mapped_column(ForeignKey("proposed_health_fact_groups.id"))
    subject_person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    fact_category: Mapped[str] = mapped_column(String(100))
    fact_code: Mapped[str] = mapped_column(String(150))
    display_name: Mapped[str] = mapped_column(String(255))
    value_type: Mapped[str | None] = mapped_column(String(50))
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    text_value: Mapped[str | None] = mapped_column(Text)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean)
    date_value: Mapped[date | None] = mapped_column(Date)
    datetime_value: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_value_text: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(100))
    original_unit: Mapped[str | None] = mapped_column(String(100))
    reference_range_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    reference_range_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    reference_range_text: Mapped[str | None] = mapped_column(String(500))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_label: Mapped[str | None] = mapped_column(String(255))
    source_locator: Mapped[str | None] = mapped_column(String(500))
    interpretation_notes: Mapped[str | None] = mapped_column(Text)
    canonical_target_type: Mapped[str | None] = mapped_column(String(100))
    canonical_status: Mapped[str] = mapped_column(String(50))
    original_proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT)
    confirmed_by_user_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_accounts.id")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_record_type: Mapped[str | None] = mapped_column(String(100))
    promoted_record_id: Mapped[UUID | None] = mapped_column()


class ProposedFactRevision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "proposed_fact_revisions"
    __table_args__ = (
        Index("ix_fact_revisions_fact_time", "proposed_health_fact_id", "created_at"),
    )

    proposed_health_fact_id: Mapped[UUID] = mapped_column(ForeignKey("proposed_health_facts.id"))
    actor_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    action: Mapped[str] = mapped_column(String(50))
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExerciseType(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exercise_types"

    code: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExerciseMetricDefinition(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exercise_metric_definitions"

    code: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    allowed_units_json: Mapped[list[Any]] = mapped_column(JSON_VARIANT)
    observation_projection_code: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExerciseSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exercise_sessions"
    __table_args__ = (Index("ix_exercise_sessions_person_time", "person_id", "started_at"),)

    person_id: Mapped[UUID] = mapped_column(ForeignKey("persons.id"))
    exercise_type_id: Mapped[UUID] = mapped_column(ForeignKey("exercise_types.id"))
    source_artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("source_artifacts.id"))
    processing_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_runs.id"))
    fact_group_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proposed_health_fact_groups.id"), unique=True
    )
    entered_by_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    confirmed_by_user_account_id: Mapped[UUID] = mapped_column(ForeignKey("user_accounts.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    source_measurement_reliability: Mapped[str] = mapped_column(String(50))


class ExerciseMetric(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exercise_metrics"
    __table_args__ = (
        UniqueConstraint("exercise_session_id", "metric_definition_id", name="uq_exercise_metric"),
    )

    exercise_session_id: Mapped[UUID] = mapped_column(ForeignKey("exercise_sessions.id"))
    metric_definition_id: Mapped[UUID] = mapped_column(ForeignKey("exercise_metric_definitions.id"))
    numeric_value: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    unit: Mapped[str] = mapped_column(String(100))
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_measurement_reliability: Mapped[str] = mapped_column(String(50))
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    proposed_health_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proposed_health_facts.id")
    )
    projected_observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("health_observations.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
