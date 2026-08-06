from dataclasses import dataclass


@dataclass(frozen=True)
class HealthFactDefinition:
    code: str
    display_name: str
    category: str
    expected_value_type: str
    allowed_units: frozenset[str]
    canonical_target: str | None


class HealthFactRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, HealthFactDefinition] = {}

    def register(self, definition: HealthFactDefinition) -> None:
        if definition.code in self._definitions:
            raise ValueError(f"Fact code already registered: {definition.code}")
        self._definitions[definition.code] = definition

    def get(self, code: str) -> HealthFactDefinition | None:
        return self._definitions.get(code)

    def all(self) -> tuple[HealthFactDefinition, ...]:
        return tuple(self._definitions.values())


def _definition(
    code: str,
    display: str,
    category: str,
    units: set[str],
    target: str | None,
) -> HealthFactDefinition:
    return HealthFactDefinition(
        code=code,
        display_name=display,
        category=category,
        expected_value_type="numeric",
        allowed_units=frozenset(units),
        canonical_target=target,
    )


registry = HealthFactRegistry()
for item in (
    _definition("body_weight", "Body weight", "biometric", {"lb", "kg"}, "health_observation"),
    _definition(
        "resting_heart_rate", "Resting heart rate", "biometric", {"bpm"}, "health_observation"
    ),
    _definition(
        "blood_pressure_systolic",
        "Systolic blood pressure",
        "biometric",
        {"mmHg"},
        "health_observation",
    ),
    _definition(
        "blood_pressure_diastolic",
        "Diastolic blood pressure",
        "biometric",
        {"mmHg"},
        "health_observation",
    ),
    _definition(
        "sleep_duration", "Sleep duration", "general_health", {"hour", "min"}, "health_observation"
    ),
    _definition("step_count", "Step count", "exercise", {"count"}, "health_observation"),
    _definition("exercise_distance", "Distance", "exercise", {"mi", "km", "m"}, "exercise_metric"),
    _definition(
        "exercise_duration", "Duration", "exercise", {"s", "min", "hour"}, "exercise_metric"
    ),
    _definition(
        "exercise_calories_burned", "Calories burned", "exercise", {"kcal"}, "exercise_metric"
    ),
    _definition("average_heart_rate", "Average heart rate", "exercise", {"bpm"}, "exercise_metric"),
    _definition("maximum_heart_rate", "Maximum heart rate", "exercise", {"bpm"}, "exercise_metric"),
    _definition("minimum_heart_rate", "Minimum heart rate", "exercise", {"bpm"}, "exercise_metric"),
    _definition("average_speed", "Average speed", "exercise", {"mph", "km/h"}, "exercise_metric"),
    _definition("maximum_speed", "Maximum speed", "exercise", {"mph", "km/h"}, "exercise_metric"),
    _definition("pace", "Pace", "exercise", {"min/mi", "min/km"}, "exercise_metric"),
    _definition("resistance_level", "Resistance", "exercise", {"level"}, "exercise_metric"),
    _definition("incline", "Incline", "exercise", {"%"}, "exercise_metric"),
    _definition("steps", "Steps", "exercise", {"count"}, "exercise_metric"),
    _definition("strides", "Strides", "exercise", {"count"}, "exercise_metric"),
    _definition("floors", "Floors", "exercise", {"count"}, "exercise_metric"),
    _definition("elevation_gain", "Elevation gain", "exercise", {"ft", "m"}, "exercise_metric"),
    _definition("cadence", "Cadence", "exercise", {"rpm", "spm"}, "exercise_metric"),
    _definition("watts", "Power", "exercise", {"W"}, "exercise_metric"),
    _definition("mets", "METs", "exercise", {"MET"}, "exercise_metric"),
    _definition("total_cholesterol", "Total cholesterol", "laboratory", {"mg/dL", "mmol/L"}, None),
    _definition("ldl_cholesterol", "LDL cholesterol", "laboratory", {"mg/dL", "mmol/L"}, None),
    _definition("hdl_cholesterol", "HDL cholesterol", "laboratory", {"mg/dL", "mmol/L"}, None),
    _definition("triglycerides", "Triglycerides", "laboratory", {"mg/dL", "mmol/L"}, None),
    _definition("glucose", "Glucose", "laboratory", {"mg/dL", "mmol/L"}, None),
    _definition("hemoglobin_a1c", "Hemoglobin A1c", "laboratory", {"%", "mmol/mol"}, None),
):
    registry.register(item)
