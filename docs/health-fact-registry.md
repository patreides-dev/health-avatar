# Health fact registry

`HealthFactRegistry` maps a stable fact code to its display name, category, expected value type,
allowed units, and optional canonical target. Registration replaces a central conditional
dispatcher and lets future domain packages add validators and promoters without changing the
provider contract.

Initial general codes include `body_weight`, `resting_heart_rate`, blood-pressure components,
`sleep_duration`, and `step_count`. The exercise vocabulary covers duration, distance, calories,
heart-rate extrema, speed, pace, resistance, incline, steps/strides/floors, elevation, cadence,
watts, and METs. Laboratory staging covers total/LDL/HDL cholesterol, triglycerides, glucose, and
hemoglobin A1c.

Registry recognition is not permission to promote. Deterministic type/unit validation runs after
extraction, and the domain promoter independently checks authorization and canonical prerequisites.
Unknown codes use `unsupported`; incomplete known codes use `unresolved` or `invalid`; all retain
their proposal and source location.
