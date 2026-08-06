# Exercise domain

The exercise session is authoritative. `ExerciseType` names the activity, `ExerciseSession` holds
session-level timing and provenance, `ExerciseMetricDefinition` controls metric units, and
`ExerciseMetric` holds user-confirmed values. Extraction confidence and source-measurement
reliability are separate fields.

AI workout facts must belong to an `exercise_session` fact group and pass review. Confirmation is
transactional and idempotent through the group's unique session relationship. A duration-only
display produces a duration without inventing a start time. Machine calorie values are stored as
machine-displayed, user-confirmed measurements, not physiological truth.

Manual entry uses the same exercise catalog and authorization boundary but has no AI proposal.
Future deterministic observation projections may be added for selected metrics; the session and
metric remain the source of truth.
