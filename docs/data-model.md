# Data model

All identifiers are UUIDs and timestamps are timezone-aware.

```mermaid
erDiagram
  USER_ACCOUNT ||--o{ APP_SESSION : owns
  USER_ACCOUNT ||--o{ ACCESS_GRANT : receives
  PERSON ||--o{ ACCESS_GRANT : authorizes
  PERSON ||--o{ SOURCE_ARTIFACT : subject
  SOURCE_SYSTEM o|--o{ SOURCE_ARTIFACT : origin
  SOURCE_ARTIFACT o|--o{ SOURCE_ARTIFACT : parent
  SOURCE_ARTIFACT ||--o{ PROCESSING_RUN : processed
  PROCESSING_RUN ||--o{ CANDIDATE_RECORD : stages
  PROCESSING_RUN ||--o{ VALIDATION_ISSUE : reports
  CANDIDATE_RECORD o|--o{ VALIDATION_ISSUE : explains
  CANDIDATE_RECORD o|--o| HEALTH_OBSERVATION : promotes
  PERSON ||--o{ HEALTH_OBSERVATION : owns
  SOURCE_ARTIFACT o|--o{ HEALTH_OBSERVATION : evidences
  PROCESSING_RUN o|--o{ HEALTH_OBSERVATION : produces
  IMPORT_BATCH o|--o{ HEALTH_OBSERVATION : compatibility
  USER_ACCOUNT ||--o{ AUDIT_EVENT : acts
```

- **UserAccount:** durable `(auth_provider, provider_subject)` identity, mutable email/profile
  metadata, verification state, pending/active/disabled status, system-administrator flag, and login
  audit time. Email is not an external key.
- **AppSession:** hash of an opaque random session token, CSRF-token hash, expiry, and invalidation
  time. Raw tokens are never stored.
- **AccessGrant:** explicit user/person role, optional caregiver approval capability, grant time,
  optional expiry/revocation, and granting/revoking actors.
- **SourceArtifact:** immutable evidence description, subject/source context, submitter, parent,
  extensible kind and sensitivity strings, hash/length, storage reference, lifecycle status, and
  metadata. Raw bytes are not relational columns.
- **ProcessingRun:** adapter identity/version/schema, requester, lifecycle, coherent counts,
  configuration, and safe error summary.
- **CandidateRecord:** typed proposed record, subject, source locator, raw/normalized candidate JSON,
  lifecycle, confidence, approval, and rejection audit fields.
- **ValidationIssue:** structured severity/code/message, optional field/candidate, and source locator.
- **HealthObservation:** typed canonical value with existing Version 0.1 provenance plus artifact,
  run, candidate, adapter, submitter, and approver links. Candidate linkage is unique.
- **ImportBatch:** retained as the Version 0.1 compatibility summary, now linked to artifact and run.
- **AuditEvent:** immutable security-administration actor/action/target record without health payloads.

Observations remain append-only. A complete correction/supersession service is deferred rather than
adding unused mutable fields. Existing observations migrate unchanged and remain queryable.

## AI intake and exercise additions

```mermaid
erDiagram
  PERSON ||--o{ AI_INTAKE_REQUEST : subject
  USER_ACCOUNT ||--o{ AI_INTAKE_REQUEST : submits
  SOURCE_ARTIFACT ||--o{ AI_INTAKE_REQUEST : evidence
  AI_INTAKE_REQUEST ||--|| AI_PROCESSING_CONSENT : records
  AI_INTAKE_REQUEST ||--o| PROCESSING_RUN : uses
  PROCESSING_RUN ||--o{ PROPOSED_HEALTH_FACT_GROUP : groups
  CANDIDATE_RECORD ||--|| PROPOSED_HEALTH_FACT : types
  PROPOSED_HEALTH_FACT_GROUP ||--o{ PROPOSED_HEALTH_FACT : contains
  PROPOSED_HEALTH_FACT ||--o{ PROPOSED_FACT_REVISION : preserves
  PROPOSED_HEALTH_FACT_GROUP ||--o| EXERCISE_SESSION : promotes
  EXERCISE_SESSION ||--o{ EXERCISE_METRIC : owns
```

The fact table permits at most one typed value and constrains confidence to 0 through 1. Original
proposals remain immutable while revision events preserve corrections, removals, and reviewer-added
facts. Unique candidate and exercise-group relationships support idempotent promotion. Laboratory
facts remain persistent staged records so panel grouping and reference ranges are not lost.
