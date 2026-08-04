from enum import StrEnum


class PersonStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class AccessRole(StrEnum):
    OWNER = "owner"
    ADMINISTRATOR = "administrator"
    CAREGIVER = "caregiver"
    VIEWER = "viewer"


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
