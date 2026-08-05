from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AdapterRequest(BaseModel):
    content: bytes
    artifact_kind: str
    media_type: str
    filename: str | None
    source_system_name: str | None
    subject_person_id: UUID | None
    people_by_reference: dict[str, UUID] = Field(default_factory=dict)
    observation_types: dict[str, tuple[UUID, str | None, str]] = Field(default_factory=dict)


class CandidateDraft(BaseModel):
    candidate_type: str
    source_locator: str
    subject_person_id: UUID | None
    status: str
    confidence: Decimal | None = None
    raw: dict[str, Any]
    normalized: dict[str, Any] | None = None


class IssueDraft(BaseModel):
    candidate_index: int | None = None
    field_name: str | None = None
    severity: str
    issue_code: str
    message: str
    source_locator: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ProcessingSummary(BaseModel):
    total: int
    valid: int
    invalid: int
    review_required: int = 0


class AdapterResult(BaseModel):
    adapter_name: str
    adapter_version: str
    schema_version: str
    candidate_records: list[CandidateDraft]
    validation_issues: list[IssueDraft]
    processing_summary: ProcessingSummary
