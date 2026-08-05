# Canonical CSV import contract

The UTF-8 header remains exactly:

```csv
person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier
```

Rows require an existing explicit person reference, active numeric observation type, timezone-aware
ISO 8601 timestamp, decimal value, exact configured unit, supported method/reliability, and source
record identifier. No person guessing or unit conversion occurs.

The Version 0.2A flow is:

```text
CSV -> SourceArtifact -> ProcessingRun -> CanonicalCsvAdapter
    -> CandidateRecord + ValidationIssue -> promotion -> HealthObservation
```

Every row becomes a candidate. Invalid rows remain `invalid` and produce structured issues; valid
trusted rows begin approved and are automatically promoted only after submit authorization.
Promotion revalidates the candidate and is idempotent. Raw accepted and rejected row dictionaries
remain protected JSON and are omitted from ordinary API responses.

Artifact identity is scoped by byte hash, source system, and selected subject context. Thus identical
bytes may legitimately create distinct artifacts for different people. Processing identity is the
artifact plus adapter name and schema version; an exact repeated operation returns the prior
artifact, run, and compatibility batch. A new schema version may create a new run over the same
artifact. Canonical duplicate protection remains source system, source record identifier, person,
and observation type. A cross-artifact conflict becomes a `promotion_failed` candidate and coherent
completed-with-errors counts rather than a duplicate observation.
