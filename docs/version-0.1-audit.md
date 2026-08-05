# Version 0.1 architectural audit

This audit was performed against commit `6bf32b5` and migration `20260804_0001`. Findings below
are limited to behavior supported by the repository.

## Findings and risks

### Authentication and authorization

- `UserAccount` contains a UUID, unique email, display name, active flag, and audit timestamps. It
  has no provider identity, email-verification state, login timestamp, or pending/administrator
  state.
- `AccessGrant` links a user to a person with `owner`, `administrator`, `caregiver`, or `viewer`, a
  grant time, and optional revocation time. It has no expiry or capability overrides and permits
  multiple simultaneous equivalent grants.
- No endpoint or shared service authenticates an actor or enforces a grant. Every person,
  observation, and import-batch read is currently broad, and every create/import route is open.
- Existing JSON contracts can mostly remain stable by adding authentication dependencies and
  actor-aware service calls. Unauthorized resource reads must use the same not-found response as
  nonexistent resources.
- `is_active` can model disabled accounts, but Version 0.1 does not check it. A pending state and
  durable provider identity are required.

### Observation provenance and mutability

- `HealthObservation` does not record its creating or approving user. It links accepted CSV rows to
  person, source system, import batch, source record identifier, row number, and exact raw row JSON.
- No observation update or delete endpoint exists. There is no correction or supersession model.
- Rejected rows are retained in `ImportError.raw_row_json`; accepted rows are retained in
  `HealthObservation.raw_source_row_json`. API response models omit both raw payloads.
- Canonical rows are traceable to an import batch and exact source row, but not to stored source
  bytes, a processing run, adapter schema version, submitter, candidate, or approver.
- Cross-file duplicate detection uses source system, source record identifier, person, and type.
  Changed identifiers can duplicate an event, while reused identifiers can suppress a legitimate
  repeat or correction.

### Import idempotency

- Request lookup is scoped by source system, SHA-256, and optional subject. Byte-identical files can
  therefore be imported for different explicitly selected people.
- Unscoped imports use a nullable subject in a SQL unique constraint. PostgreSQL treats nulls as
  distinct, so the application lookup handles normal reruns but the constraint does not close a
  concurrent unscoped-import race.
- Adapter/version is not part of the key, so a file cannot intentionally be reprocessed by a
  materially newer adapter.
- Parsed-row counts, observations, and row errors commit together. Header/encoding failures commit
  a failed batch separately. An integrity failure rolls back the whole parsed result and attempts
  to return a competing batch, preserving consistency but losing a structured failure when the
  conflict is unrelated.

### Device assignments

- Pydantic and database checks reject an end at or before the start.
- Overlapping assignments are allowed. No schema field distinguishes exclusive from shared devices,
  and no service defines overlap policy.
- Imports do not resolve device attribution at observation time; observations accept an explicit
  optional device only. Version 0.2A will preserve this behavior and defer exclusive-device overlap
  and temporal attribution policy.

### API and operational safety

- Observation pagination orders by observed time descending and UUID; person listing orders by
  creation time and UUID. Existing pagination is deterministic, though person listing has no limit.
- Application code has no raw-row logging. Raw rows are stored in protected JSON columns. Generic
  database errors are converted to a fixed internal-error response without exception detail.
- CSV uploads have no byte limit, media-type check, or extension check and are read entirely into
  memory.
- Original file bytes are not stored; only filename, SHA-256, raw parsed rows, and normalized data
  are retained.
- Tracked fixtures and examples are visibly synthetic. No repository file examined contains real
  health data or credentials.

## Version 0.2A changes required

- Add Google OIDC provider-subject identity, pending provisioning, secure server sessions, isolated
  development authentication, and startup security validation.
- Add actor-aware authorization services and enforce them for every person-scoped or administrative
  API, browser, ingestion, promotion, and CLI operation.
- Add immutable source artifacts backed by safe storage, processing runs, typed candidates,
  validation issues, promotion provenance, and security audit events.
- Refactor canonical CSV into a registered adapter and intentionally scope idempotency by artifact
  hash, source system, subject context, adapter, and schema/major version.
- Add upload restrictions, bounded deterministic pagination, responsive authenticated pages, CSRF
  protection, and review/administration workflows.

## Compatibility decisions

- Preserve Version 0.1 route paths and response fields where practical; those routes now require an
  authenticated session and authorization.
- Preserve `ImportBatch` as a compatibility summary while making `SourceArtifact` and
  `ProcessingRun` the universal ingestion lifecycle.
- Preserve exact raw-row retention and existing canonical CSV validation semantics.
- Keep observations append-only. A complete correction service is deferred instead of adding
  unused columns without coherent behavior.
- Treat administrator as a system role only; administrators do not receive implicit health-data
  read access.

## Explicitly deferred

- Device exclusivity/overlap enforcement and automatic observation-time device attribution.
- Full non-destructive correction and supersession workflow.
- Malware scanning and encrypted cloud object storage.
- Background processing, production multimodal/AI calls, OCR, nutrition, wearable, and medical
  document adapters.
- Public deployment and regulatory certification.
