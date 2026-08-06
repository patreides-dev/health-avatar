# Health Avatar project status

Last verified: 2026-08-05 (America/New_York)

This is the durable continuation checkpoint. Read this file first, then `README.md`,
`docs/architecture.md`, `docs/data-model.md`, `docs/import-contract.md`, and the version audit.

## Repository state

- Repository: `patreides-dev/health-avatar`
- Checkout: `C:\patreides-repos\health-avatar`
- Current branch: `version-0.2b-ai-intake`
- Remote: `git@github-personal:patreides-dev/health-avatar.git`
- Version 0.1 main baseline: `6bf32b5` (`docs: add fresh-thread continuation checkpoint`)
- Version 0.2A merge commit: `3306046` (`merge: release Version 0.2A secure ingestion foundation`)
- Annotated release tag: `v0.2.0-alpha.1`
- Reviewed Version 0.2A feature head: `999d23f`
- Migration head: `20260805_0003`, following `20260805_0002` and `20260804_0001`

Version 0.2A passed its independent merge gate and is merged and pushed to `main`. The gate found
and corrected two authorization-boundary defects before merge: CSV validation context could
distinguish an unauthorized person reference from a nonexistent one, and inconsistent account
status flags were not checked uniformly in all browser, CLI, session, and grant paths. Regression
tests cover both corrections.

## Version 0.2A scope and implementation

Version 0.2A establishes secure identity and source-agnostic ingestion. It provides:

- Google OpenID Connect identity verification through `google-auth`, durable mapping by provider
  subject, pending account provisioning, and no stored Google access or refresh tokens.
- Server-side opaque sessions with HTTP-only/SameSite cookies, production Secure cookies,
  expiration, logout invalidation, signed OIDC state/nonce, CSRF protection, and rotatable secrets.
- An isolated, visibly labeled deterministic development login that is disabled by default and
  rejected by production configuration validation.
- Service-layer `AccessGrant` enforcement with owner, administrator, caregiver, and viewer policy;
  active/expiry/revocation checks; resource-hiding 404s; and no household-derived permissions.
  System administrators do not receive blanket health-record access.
- Audited account activation/disable and access-grant/revoke operations through protected APIs and
  trusted local CLI commands with explicit actor context.
- Immutable source-artifact metadata and locally stored bytes behind an `ArtifactStorage`
  abstraction with generated keys, path confinement, hash calculation, and size/type restrictions.
- A typed ingestion adapter contract and registry, processing runs, candidate records, structured
  validation issues, human approval/rejection metadata, and idempotent canonical promotion.
- A fully functional `CanonicalCsvAdapter`. CSV now flows through artifact, run, candidate,
  validation, and promotion records while retaining Version 0.1 import batches/errors and accepted
  raw-row provenance for compatibility.
- Provenance from every promoted observation to artifact, run, candidate, adapter/version,
  submitter, approver, person, and source locator.
- Responsive server-rendered login, pending-account, person-selector, person-summary, upload,
  processing-run, and candidate-review pages. Pages escape source-controlled values and never
  reveal storage keys or raw artifact bytes.
- Versioned JSON APIs and expanded administrative/inspection CLI commands described in `README.md`.
- Synthetic seed accounts for owner, viewer, caregiver, pending, administrator, and revoked-access
  scenarios. No seed identity or sample is a real person.

## Important policies and invariants

- Authentication proves identity; only active `AccessGrant` records authorize person data.
- A successful first Google login creates a pending internal account and grants no health access.
- Email is mutable profile metadata, not the durable external identity key. Unverified email is not
  trusted.
- Owners can grant ordinary caregiver/viewer access for their person. System administration is
  required for account lifecycle and broader grant operations. Self-escalation is prohibited.
- Viewer is read-only. Caregiver may submit and may approve only when `can_approve` is set. Owner may
  submit, approve, and manage ordinary access. Administrators read health data only with a grant.
- Unauthorized object lookups use 404 when revealing existence is unnecessary; unauthenticated
  requests use 401 and authenticated capability failures use structured 403/404 responses.
- Artifact idempotency is scoped by byte hash, source system, and subject/unresolved context.
  Processing idempotency adds adapter name and schema version. A newer schema version can reprocess
  an artifact; candidate-to-observation uniqueness prevents duplicate promotion.
- Source evidence is not silently deleted when canonical data changes. Full correction/supersession
  support remains deferred rather than making observations destructively mutable.
- Raw artifact contents and rejected rows must not be logged or returned by ordinary APIs.
- Real health data, credentials, `.env`, dumps, and artifact-storage contents must never enter Git.
- The deployment remains private and non-public pending an explicit security and operations review.

## Version 0.2B scope and implementation

Version 0.2B extends the verified Version 0.2A boundaries with:

- Provider-neutral text/image extraction contracts, strict structured output, a deterministic mock
  provider, and an official-SDK OpenAI provider that is disabled until cloud use, credentials, and
  an explicit model are configured.
- Per-intake disclosure/consent records, global cloud disablement, maximum sensitivity policy,
  identity/context minimization, prompt-injection resistance, and no raw content or secrets in logs.
- `AIIntakeRequest`, grouped typed `ProposedHealthFact` records, immutable original proposals,
  review revisions, unsupported/unresolved persistence, and a registry of value types, units, and
  domain targets.
- Mandatory review for every AI fact. Reviewers may correct, remove, or add registered facts.
  Promotion is authorized, audited, transactional, and idempotent; AI output never writes canonical
  tables directly.
- Safe JPEG/PNG/WebP intake with actual-format verification, byte/pixel/dimension limits,
  decompression-bomb/corruption handling, private originals, and EXIF-free provider bytes.
- An authoritative exercise domain with exercise types, sessions, metric definitions, metrics,
  manual entry, and workout-image promotion without fabricated start times.
- A non-exercise laboratory demonstration covering total/LDL/HDL cholesterol, triglycerides,
  glucose, and A1c. Reviewed facts retain panel grouping, units, dates, and reference ranges but stay
  staged until a coherent canonical laboratory domain is introduced.
- Responsive add-health, workout-photo, grouped review, and recent-intake pages plus versioned APIs.

See `docs/ai-health-intake.md`, `docs/health-fact-registry.md`, `docs/exercise-domain.md`,
`docs/workout-image-ingestion.md`, `docs/multimodal-providers.md`, and `docs/ai-privacy.md`.

## Verification checkpoint

Evidence run on the final Version 0.2A working tree:

- PostgreSQL-backed Docker test suite: 53 passed; 78% branch-aware coverage. It includes a populated
  Version 0.1 database upgrade to head, data-preservation checks, downgrade, and upgrade back to
  Version 0.2A.
- Ruff format check and Ruff lint: passed for 59 files.
- Strict MyPy: passed for 34 application source files.
- Pre-commit: both pinned Ruff hooks passed.
- Alembic autogenerate drift check: no new upgrade operations detected.
- Docker image: built successfully.
- Compose: PostgreSQL and application both healthy; `/health` returned
  `{"status":"ok","version":"0.2.0"}`.
- Migration/seed/validation: upgrade reached head; repeated synthetic seed runs created zero
  duplicates; `health-avatar validate` passed.
- Live development authentication: owner and viewer sessions succeeded; pending access returned
  403; viewer upload returned the resource-hiding 404; a temporarily activated synthetic identity
  with only a revoked grant received an empty person list.
- Live owner CLI import: completed with 3 candidates, 3 promoted observations, 0 rejected; artifact,
  run, candidate, and observation provenance links were present.

The suite emits one non-failing dependency warning: the installed FastAPI/Starlette TestClient
reports that its current `httpx` integration is deprecated in favor of `httpx2`.

## Known limitations and explicitly deferred work

- A real Google browser login was not exercised because repository-safe client credentials were not
  available. Token validation, account mapping, callback/session behavior, invalid/audience/expiry
  failures, and disabled/pending accounts are covered with mocks and deterministic tests. Google
  Cloud client registration and an authorized redirect URI still require manual validation.
- Local filesystem storage is development-only. Encrypted object storage, malware scanning,
  backup/restore drills, TLS termination, and production secrets infrastructure are not supplied.
- Canonical CSV remains the only deterministic source adapter. Text and simple images use reviewed
  provider extraction; PDF/complex documents and generic OCR remain deferred.
- Observation correction/supersession remains a documented future non-destructive service design.
- Device assignment ranges are validated but overlap/exclusivity policy remains deferred.
- No live OpenAI call, generic OCR, meal/nutrition interpretation, canonical laboratory domain,
  Samsung or Hume connector, medical-document extraction, diagnostics, treatment advice, public
  deployment, native Android app, React SPA, background jobs, or broad analytics are included.

## Version 0.2B verification checkpoint

- Local suite: 66 passed, 3 PostgreSQL-only skipped; 82% branch-aware coverage.
- PostgreSQL-backed Docker suite: 69 passed; 82% coverage. Its migration test populated Version
  0.1, upgraded to `20260805_0003`, preserved data, downgraded to Version 0.1, and upgraded to head.
- Ruff formatting/lint, strict MyPy (40 application files), all pinned pre-commit hooks, and Alembic
  autogenerate drift check passed.
- Docker image rebuilt; PostgreSQL and application became healthy; `/health` returned
  `{"status":"ok","version":"0.2.0b1"}`.
- Repeated synthetic seed runs created zero duplicates; `health-avatar validate` passed.
- A temporary intentionally enabled development-auth container completed an owner four-fact lipid
  intake and review, while the viewer submission returned the resource-hiding 404.
- No real Google login or live OpenAI request was performed; both external integrations remain
  covered with mocks and require manual credential/configuration validation.

## Next intended scope

Version 0.2C should build a conversational meal workflow with a provider-neutral nutrition matcher,
structured foods, uncertainty, and explicit review. It should also decide whether to introduce the
canonical laboratory panel/result domain now that reviewed laboratory facts establish its boundary.

## Fresh-thread startup checklist

```powershell
cd C:\patreides-repos\health-avatar
git status --short --branch
git fetch origin
git log --oneline --decorate -n 12
docker compose up --build -d
docker compose exec app health-avatar db upgrade
docker compose exec app health-avatar seed development
docker compose exec app health-avatar validate
Invoke-RestMethod http://localhost:8000/health
```

Before changing code, inspect the current branch, migrations, tests, documentation, and history.
Do not begin the next version until its exact scope is explicitly established.
