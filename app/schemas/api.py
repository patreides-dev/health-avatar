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
