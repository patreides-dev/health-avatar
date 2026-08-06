from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import MeasurementMethod, PersonStatus, ReliabilityClassification


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PersonCreate(BaseModel):
    external_reference: str | None = Field(default=None, max_length=255)
    preferred_name: str = Field(min_length=1, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    date_of_birth: date | None = None
    timezone: str = "UTC"
    status: PersonStatus = PersonStatus.ACTIVE

    @model_validator(mode="after")
    def validate_timezone(self) -> "PersonCreate":
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return self


class PersonRead(ORMModel):
    id: UUID
    external_reference: str | None
    preferred_name: str
    legal_name: str | None
    date_of_birth: date | None
    timezone: str
    status: str
    created_at: datetime
    updated_at: datetime


class SourceSystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=100)
    vendor: str = Field(min_length=1, max_length=255)
    version: str | None = None
    description: str | None = None


class SourceSystemRead(ORMModel):
    id: UUID
    name: str
    source_type: str
    vendor: str
    version: str | None
    description: str | None
    created_at: datetime


class DeviceCreate(BaseModel):
    source_system_id: UUID | None = None
    manufacturer: str
    model: str
    device_type: str
    serial_number: str | None = None
    external_device_id: str | None = None


class DeviceRead(ORMModel):
    id: UUID
    source_system_id: UUID | None
    manufacturer: str
    model: str
    device_type: str
    serial_number: str | None
    external_device_id: str | None
    created_at: datetime


class DeviceAssignmentCreate(BaseModel):
    person_id: UUID
    device_id: UUID
    assigned_from: datetime
    assigned_until: datetime | None = None
    assignment_type: str

    @model_validator(mode="after")
    def valid_range(self) -> "DeviceAssignmentCreate":
        if self.assigned_until is not None and self.assigned_until <= self.assigned_from:
            raise ValueError("assigned_until must be after assigned_from")
        return self


class DeviceAssignmentRead(ORMModel):
    id: UUID
    person_id: UUID
    device_id: UUID
    assigned_from: datetime
    assigned_until: datetime | None
    assignment_type: str
    created_at: datetime


class ImportBatchRead(ORMModel):
    id: UUID
    source_system_id: UUID
    subject_person_id: UUID | None
    original_filename: str
    file_sha256: str
    status: str
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    importer_name: str
    importer_version: str
    import_started_at: datetime
    import_completed_at: datetime | None


class ObservationRead(ORMModel):
    id: UUID
    person_id: UUID
    observation_type_id: UUID
    observation_type: "ObservationTypeRead"
    observed_at: datetime
    observed_until: datetime | None
    numeric_value: Decimal | None
    text_value: str | None
    boolean_value: bool | None
    unit: str | None
    source_system_id: UUID
    device_id: UUID | None
    import_batch_id: UUID | None
    source_record_identifier: str | None
    source_row_number: int | None
    measurement_method: str
    reliability_classification: str
    created_at: datetime


class ObservationTypeRead(ORMModel):
    id: UUID
    code: str
    display_name: str
    default_unit: str | None
    value_type: str
    category: str


class ObservationPage(BaseModel):
    items: list[ObservationRead]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class MeRead(ORMModel):
    id: UUID
    email: str
    email_verified: bool
    display_name: str
    profile_image_url: str | None
    account_status: str
    is_active: bool
    is_system_administrator: bool


class ArtifactRead(ORMModel):
    id: UUID
    subject_person_id: UUID | None
    source_system_id: UUID | None
    submitted_by_user_account_id: UUID
    parent_artifact_id: UUID | None
    artifact_kind: str
    media_type: str
    original_filename: str | None
    original_external_reference: str | None
    file_sha256: str | None
    content_length: int | None
    captured_at: datetime | None
    received_at: datetime
    processing_status: str
    sensitivity_classification: str
    metadata_json: dict[str, object]
    created_at: datetime
    updated_at: datetime


class ProcessingRunRead(ORMModel):
    id: UUID
    source_artifact_id: UUID
    adapter_name: str
    adapter_version: str
    schema_version: str
    requested_by_user_account_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: str
    candidate_count: int
    accepted_count: int
    rejected_count: int
    review_required_count: int
    error_summary: str | None


class CandidateRead(ORMModel):
    id: UUID
    processing_run_id: UUID
    subject_person_id: UUID | None
    candidate_type: str
    source_locator: str
    status: str
    confidence: Decimal | None
    normalized_candidate_json: dict[str, object] | None
    approved_by_user_account_id: UUID | None
    approved_at: datetime | None
    rejected_by_user_account_id: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None


class CandidateReject(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class AITextIntakeCreate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    purpose: str = Field(default="general_health", max_length=100)
    sensitivity: str = Field(default="general_health", max_length=100)
    consent: bool


class AIIntakeRead(ORMModel):
    id: UUID
    person_id: UUID
    source_artifact_id: UUID
    processing_run_id: UUID | None
    input_modality: str
    intake_purpose: str
    provider_name: str
    model_name: str
    prompt_template_name: str
    prompt_version: str
    output_schema_version: str
    status: str
    submission_summary: str | None
    unresolved_content: list[object]
    overall_confidence: Decimal | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class ProposedHealthFactRead(ORMModel):
    id: UUID
    processing_run_id: UUID
    candidate_record_id: UUID
    fact_group_id: UUID | None
    subject_person_id: UUID
    fact_category: str
    fact_code: str
    display_name: str
    value_type: str | None
    numeric_value: Decimal | None
    text_value: str | None
    boolean_value: bool | None
    date_value: date | None
    datetime_value: datetime | None
    unit: str | None
    original_unit: str | None
    reference_range_low: Decimal | None
    reference_range_high: Decimal | None
    reference_range_text: str | None
    observed_at: datetime | None
    confidence: Decimal | None
    source_label: str | None
    source_locator: str | None
    interpretation_notes: str | None
    canonical_target_type: str | None
    canonical_status: str
    confirmed_by_user_account_id: UUID | None
    confirmed_at: datetime | None
    promoted_record_type: str | None
    promoted_record_id: UUID | None


class FactRevisionRequest(BaseModel):
    numeric_value: Decimal | None = None
    unit: str | None = Field(default=None, max_length=100)
    observed_at: datetime | None = None
    remove: bool = False
    reason: str | None = Field(default=None, max_length=1000)


class FactAddRequest(BaseModel):
    fact_code: str = Field(min_length=1, max_length=150)
    numeric_value: Decimal
    unit: str = Field(min_length=1, max_length=100)
    observed_at: datetime | None = None
    group_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class IntakeRejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class ExerciseMetricCreate(BaseModel):
    code: str
    value: Decimal
    unit: str


class ExerciseSessionCreate(BaseModel):
    exercise_type: str
    started_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=2000)
    metrics: list[ExerciseMetricCreate] = Field(default_factory=list)


class ExerciseSessionRead(ORMModel):
    id: UUID
    person_id: UUID
    exercise_type_id: UUID
    source_artifact_id: UUID | None
    processing_run_id: UUID | None
    fact_group_id: UUID | None
    entered_by_user_account_id: UUID
    confirmed_by_user_account_id: UUID
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    notes: str | None
    source_measurement_reliability: str
    created_at: datetime


class AccessGrantCreate(BaseModel):
    user_account_id: UUID
    person_id: UUID
    role: str
    can_approve: bool = False
    expires_at: datetime | None = None


class CanonicalObservationRow(BaseModel):
    person_external_reference: str
    observation_type: str
    observed_at: datetime
    value: Decimal
    unit: str
    measurement_method: MeasurementMethod
    reliability_classification: ReliabilityClassification
    source_record_identifier: str

    @model_validator(mode="after")
    def timezone_required(self) -> "CanonicalObservationRow":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include an explicit timezone offset")
        return self
