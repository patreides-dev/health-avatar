# Universal AI-assisted health intake

Version 0.2B accepts authorized text and JPEG, PNG, or WebP evidence through the Version 0.2A
artifact and processing foundations. Purpose (`general_health`, `exercise`, `laboratory`, and other
hints) affects routing only; it never limits what the extractor may report.

## Invariants

The pipeline is `SourceArtifact → AIIntakeRequest → ProcessingRun → CandidateRecord →
ProposedHealthFact → deterministic validation → review → domain promoter`. A language model never
writes canonical tables. Every AI fact requires human review. Original proposals, corrections,
removals, additions, consent, actor, provider/model, prompt/schema versions, source locator, and
promotion target remain queryable.

Exactly one typed fact value may be set. Values without a unit, ambiguous values, and unknown fact
codes stay staged. Confidence is extraction confidence from 0 through 1; it is not measurement
reliability or clinical significance. Reference ranges are retained exactly as source metadata and
are never interpreted as universal standards.

## Supported routing

- Body weight, resting heart rate, blood-pressure components, sleep duration, and steps can route
  to `HealthObservation` after required fields and time are reviewed.
- Exercise groups route transactionally to `ExerciseSession` and `ExerciseMetric`.
- The initial lipid/glucose/A1c vocabulary is extracted, grouped, reviewed, and retained, but its
  canonical laboratory domain is deliberately deferred.
- Any other explicit fact is stored as unsupported/unmapped staged evidence. It is never silently
  discarded or represented as a fake generic observation.

Text input works with phone keyboard dictation; there is no speech-provider coupling. PDF and
complex document extraction, meal/nutrition matching, medication reconciliation, symptom triage,
diagnosis, and treatment advice are deferred.
