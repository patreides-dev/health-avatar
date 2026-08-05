import csv
import io
from typing import Any

from pydantic import ValidationError

from app.ingestion.contracts import (
    AdapterRequest,
    AdapterResult,
    CandidateDraft,
    IssueDraft,
    ProcessingSummary,
)
from app.models.enums import CandidateStatus, ValueType
from app.schemas.api import CanonicalObservationRow

EXPECTED_COLUMNS = {
    "person_external_reference",
    "observation_type",
    "observed_at",
    "value",
    "unit",
    "measurement_method",
    "reliability_classification",
    "source_record_identifier",
}


class CanonicalCsvAdapter:
    name = "canonical_csv"
    version = "0.2.0"
    schema_version = "1"
    artifact_kinds = frozenset({"file"})
    media_types = frozenset({"text/csv", "application/csv", "application/vnd.ms-excel"})
    extensions = frozenset({".csv"})

    def inspect(self, request: AdapterRequest) -> AdapterResult:
        try:
            text = request.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must be UTF-8 encoded") from exc
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None or set(reader.fieldnames) != EXPECTED_COLUMNS:
            raise ValueError("CSV header does not exactly match the canonical contract")
        candidates: list[CandidateDraft] = []
        issues: list[IssueDraft] = []
        for row_number, raw_row in enumerate(reader, start=2):
            row: dict[str, Any] = dict(raw_row)
            locator = f"row:{row_number}"
            candidate = CandidateDraft(
                candidate_type="health_observation",
                source_locator=locator,
                subject_person_id=None,
                status=CandidateStatus.INVALID,
                raw=row,
            )
            code, message, field = "", "", None
            try:
                parsed = CanonicalObservationRow.model_validate(row)
            except ValidationError:
                code, message = "invalid_row", "Row does not satisfy the canonical CSV contract"
            else:
                person_id = request.people_by_reference.get(parsed.person_external_reference)
                type_data = request.observation_types.get(parsed.observation_type)
                if person_id is None:
                    code, message, field = (
                        "unknown_person",
                        "Person not found",
                        "person_external_reference",
                    )
                elif (
                    request.subject_person_id is not None and person_id != request.subject_person_id
                ):
                    code, message, field = (
                        "person_mismatch",
                        "Row person does not match selected subject",
                        "person_external_reference",
                    )
                elif type_data is None:
                    code, message, field = (
                        "unknown_observation_type",
                        "Unknown observation type",
                        "observation_type",
                    )
                elif type_data[2] != ValueType.NUMERIC:
                    code, message, field = (
                        "unsupported_value_type",
                        "CSV value must be numeric",
                        "value",
                    )
                elif parsed.unit != type_data[1]:
                    code, message, field = (
                        "invalid_unit",
                        f"Expected unit {type_data[1]!r}; no conversion was performed",
                        "unit",
                    )
                else:
                    candidate.subject_person_id = person_id
                    candidate.status = CandidateStatus.APPROVED
                    candidate.normalized = {
                        "observation_type_id": str(type_data[0]),
                        "observed_at": parsed.observed_at.isoformat(),
                        "numeric_value": str(parsed.value),
                        "unit": parsed.unit,
                        "measurement_method": parsed.measurement_method,
                        "reliability_classification": parsed.reliability_classification,
                        "source_record_identifier": parsed.source_record_identifier,
                        "source_row_number": row_number,
                    }
            candidates.append(candidate)
            if code:
                issues.append(
                    IssueDraft(
                        candidate_index=len(candidates) - 1,
                        field_name=field,
                        severity="error",
                        issue_code=code,
                        message=message,
                        source_locator=locator,
                    )
                )
        invalid = sum(candidate.status == CandidateStatus.INVALID for candidate in candidates)
        return AdapterResult(
            adapter_name=self.name,
            adapter_version=self.version,
            schema_version=self.schema_version,
            candidate_records=candidates,
            validation_issues=issues,
            processing_summary=ProcessingSummary(
                total=len(candidates), valid=len(candidates) - invalid, invalid=invalid
            ),
        )


registry_adapter = CanonicalCsvAdapter()
