from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class HealthExtractionFact(BaseModel):
    fact_code: str = Field(min_length=1, max_length=150)
    display_name: str = Field(min_length=1, max_length=255)
    value_type: Literal["numeric", "text", "boolean", "date", "datetime"]
    value: Decimal | str | bool | date | datetime | None = None
    unit: str | None = None
    observed_at: datetime | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_label: str | None = None
    source_locator: str | None = None
    interpretation_notes: str | None = None
    group_identifier: str | None = None
    reference_range_low: Decimal | None = None
    reference_range_high: Decimal | None = None
    reference_range_text: str | None = None


class HealthExtractionGroup(BaseModel):
    group_identifier: str
    group_type: str
    display_name: str


class HealthExtractionResponse(BaseModel):
    submission_summary: str
    detected_fact_groups: list[HealthExtractionGroup] = Field(default_factory=list)
    proposed_health_facts: list[HealthExtractionFact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unresolved_content: list[str] = Field(default_factory=list)
    overall_confidence: Decimal | None = Field(default=None, ge=0, le=1)


class HealthExtractionRequest(BaseModel):
    modality: Literal["text", "image", "document", "mixed", "api_payload"]
    purpose: str
    user_text: str | None = None
    media_type: str | None = None
    artifact_bytes: bytes | None = None
    sensitivity: str = "general_health"

    @model_validator(mode="after")
    def require_input(self) -> "HealthExtractionRequest":
        if not self.user_text and not self.artifact_bytes:
            raise ValueError("Text or artifact content is required")
        return self
