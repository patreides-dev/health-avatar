from enum import StrEnum


class PersonStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AccessRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    CAREGIVER = "caregiver"
    VIEWER = "viewer"


class AccountStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CandidateStatus(StrEnum):
    PENDING_VALIDATION = "pending_validation"
    INVALID = "invalid"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    PROMOTION_FAILED = "promotion_failed"


class ImportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class ValueType(StrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    BOOLEAN = "boolean"


class MeasurementMethod(StrEnum):
    MEASURED = "measured"
    ESTIMATED = "estimated"
    SELF_REPORTED = "self_reported"
    IMPORTED = "imported"
    CALCULATED = "calculated"
    INFERRED = "inferred"


class ReliabilityClassification(StrEnum):
    CLINICAL = "clinical"
    CONSUMER_DEVICE = "consumer_device"
    SELF_REPORTED = "self_reported"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class AIIntakeStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class FactStatus(StrEnum):
    AWAITING_REVIEW = "awaiting_review"
    UNSUPPORTED = "unsupported"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class FactValueType(StrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
