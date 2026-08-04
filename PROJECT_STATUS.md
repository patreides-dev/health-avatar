# Health Avatar project status

Last verified: 2026-08-04 (America/New_York)

This is the durable continuation checkpoint for a fresh development thread. Read this file first,
then `README.md`, `docs/architecture.md`, `docs/data-model.md`, and `docs/import-contract.md`.

## Repository state

- Repository: `patreides-dev/health-avatar`
- Local checkout used for Version 0.1: `C:\patreides-repos\health-avatar`
- Branch: `main`
- Remote transport: `git@github-personal:patreides-dev/health-avatar.git`
- Version 0.1 implementation/documentation baseline: `122314b1d77cebd7fdcf10759668730a3881731d`
- Baseline subject: `docs: document architecture privacy and roadmap`
- Handoff expectation: the documentation commit containing this file follows that baseline, is
  pushed to `origin/main`, and leaves a clean worktree. Confirm with:

```sh
git status --short --branch
git log --oneline --decorate -n 10
git rev-parse HEAD
```

The Version 0.1 work was built as seven logical commits: tooling, schema/migration, shared services,
CSV import/CLI, API, tests, and documentation. No Version 0.2 implementation is present.

## Implemented Version 0.1

Version 0.1 is a working backend-first vertical slice using Python 3.12, FastAPI, Pydantic,
SQLAlchemy 2, Alembic, PostgreSQL 16, Typer, Pytest, Ruff, MyPy, and Docker Compose.

The repository currently provides:

- Docker Compose application and PostgreSQL services, with a PostgreSQL health check and an app
  entrypoint that applies Alembic migrations before starting Uvicorn.
- A first migration, `20260804_0001`, containing the complete multi-person foundation. Migrations
  contain schema only and never create a person.
- `Person` as the first-class health-data subject with an immutable UUID and optional unique
  external reference.
- Separate `UserAccount` and `AccessGrant` entities. A login identity is not a health-data person.
  Grant roles exist in the schema but are not enforced in Version 0.1.
- Households and temporal household memberships. Membership never implies access.
- Source systems, reusable devices, and temporal person-device assignments. Shared devices are
  supported and invalid assignment ranges are rejected by validation and the database.
- Observation types and health observations with timezone-aware timestamps, explicit units, exactly
  one typed value, provenance fields, and database constraints.
- Import batches and import errors with statistics, status, SHA-256 file identity, source row
  numbers, stable error codes, and raw rejected rows.
- Exact raw canonical CSV fields retained as protected JSONB for accepted observations; raw rows are
  intentionally omitted from API responses.
- An idempotent canonical CSV importer shared by the CLI and API. It never creates an unknown person
  and never converts a unit silently.
- An idempotent development seed with six observation types, synthetic `kevin-demo`, and
  `manual-csv`. This identity exists only in the seed and synthetic example data.
- Required Version 0.1 HTTP endpoints, observation filters/pagination, structured HTTP/validation
  errors, generated OpenAPI documentation, `/health`, and a minimal HTML status page.
- A shared repository/service boundary so future web clients do not require backend restructuring.

The canonical implementation references are:

- `app/models/entities.py` for the relational model and constraints.
- `alembic/versions/20260804_0001_initial_schema.py` for the deployed schema.
- `app/importers/canonical_csv.py` for import validation, provenance, and idempotency.
- `app/services/` and `app/repositories/` for shared business/query behavior.
- `app/api/v1/router.py` and `app/cli/main.py` for the two adapters.

## Important decisions and invariants

- Privacy first: real health data, exports, documents, credentials, `.env`, database dumps, and local
  secrets must not enter Git. Tracked sample data is synthetic.
- Multi-person from migration one: a person is an entity, not a tag, and every observation belongs
  to exactly one person.
- Identity is explicit: imports resolve `person_external_reference`; unknown people are rejected.
- Units are explicit: the canonical importer requires the observation type's exact unit and performs
  no conversion.
- Raw, normalized, and future derived data remain separate. Derived values must eventually carry
  algorithm/version/input lineage and must not overwrite normalized observations.
- Provenance is mandatory: normalized observations link to person, source system, import batch,
  original filename/hash through the batch, source record identifier, and source row number.
- Accepted and rejected rows validate independently. Accepted rows commit even when other rows fail.
- File reruns are idempotent by source system, SHA-256, and optional explicit subject. Cross-file
  observation duplication uses source system, source record identifier, person, and observation
  type.
- Household membership is organizational only and must never become an implicit permission grant.
- A device assignment is temporal; no code may assume permanent one-person ownership.
- Version 0.1 does not diagnose, recommend treatment, or claim clinical interpretation.
- The API and CLI must continue to share business services rather than duplicating endpoint logic.

## Validation checkpoint

The following evidence was current on 2026-08-04:

- `ruff format --check .`: passed; 37 files already formatted.
- `ruff check .`: passed.
- `mypy app`: passed in strict mode; 24 source files checked.
- Local `pytest -q`: 12 passed, 2 PostgreSQL tests skipped because
  `HEALTH_AVATAR_TEST_DATABASE_URL` was not set, 76% coverage.
- Compose-network PostgreSQL run: 14 passed, 76% coverage. This included PostgreSQL 16 connectivity
  and an actual invalid device-assignment insert rejected by the database constraint.
- Docker application image: built successfully.
- Compose services: app running on port 8000; PostgreSQL healthy.
- Alembic: `20260804_0001 (head)`.
- Development seed: first run created six observation types, one synthetic person, and one source;
  second run created zero records.
- Example import: one completed batch with 3 total, 3 accepted, 0 rejected; rerunning returned the
  same batch and did not duplicate observations.
- Raw accepted-row provenance: present for all three example observations.
- Live health response: `{"status":"ok","version":"0.1.0"}`.

The local Docker volume contains only this synthetic demonstration state and is not a durable source
of project truth. A fresh thread may stop the stack normally with `docker compose down`; do not use
`-v` if local development data needs to be retained.

One non-failing warning remains: the installed FastAPI/Starlette TestClient reports that its current
`httpx` integration is deprecated in favor of `httpx2`. This is dependency-level follow-up, not a
Version 0.1 functional failure.

## Known limitations and unresolved items

- Authentication and authorization are not implemented or enforced. `AccessGrant` is schema only.
  Version 0.1 must remain private and must not be exposed publicly.
- The application does not orchestrate encryption at rest, HTTPS, secret management, backups, or a
  protected production object store.
- Original CSV rows are retained, and file identity is retained by filename and SHA-256, but the
  original file bytes are not stored by the application.
- Duplicate detection relies on stable upstream source record identifiers. It can miss duplicates
  when identifiers change and can reject legitimate corrections or repeated events that reuse an
  identifier. Source-native revision semantics are future work.
- Only the canonical numeric CSV contract is implemented. Text/boolean manual observations require
  a future validated service contract.
- There is no responsive frontend, manual-entry workflow, wearable connector, document ingestion,
  analytics layer, unit conversion, or clinical interpretation.
- Most service/API tests use isolated SQLite fixtures for speed. PostgreSQL-specific integration
  tests and the live vertical-slice verification cover PostgreSQL behavior, but broader end-to-end
  PostgreSQL fixture coverage would strengthen the suite.
- Compose has a PostgreSQL health check but no application health check. `docker compose up -d` can
  return just before the app entrypoint migration finishes; automation should poll `/health` before
  running seed/import commands.
- API/service coverage is meaningful but uneven; total coverage is 76%, with CLI paths and several
  error branches below the project average.

## Intended Version 0.2 direction

Do not treat this section as authorization to start Version 0.2. It records the intended next phase
for a new, explicitly scoped assignment.

Version 0.2 should add a responsive web interface and validated manual entry while preserving the
Version 0.1 boundaries. A sensible planning order is:

1. Define the manual-observation contract, including typed values, explicit units, timezone-aware
   observation times, source/provenance semantics, and validation/error behavior.
2. Add the shared manual-entry service and API endpoint with database and API tests. Manual entries
   should use an explicit source system and an appropriate measurement method such as
   `self_reported`; they must not bypass provenance or create people implicitly.
3. Add a small responsive web client that consumes `/api/v1` and does not embed business rules that
   belong in backend services.
4. Add privacy-focused UX: clear person selection, unit display, provenance display, confirmation,
   and warnings that the system is not medical advice.
5. Improve repeatable end-to-end PostgreSQL test setup and add an application health check as
   enabling work if included in the Version 0.2 scope.

Unless explicitly reprioritized, full family authentication/access-control enforcement remains a
later roadmap phase. Any Version 0.2 deployment must therefore remain private and non-public.

## Fresh-thread startup checklist

```sh
cd C:\patreides-repos\health-avatar
git status --short --branch
git fetch origin
git log --oneline --decorate -n 10
docker compose ps
docker compose up --build -d
docker compose exec app alembic current
docker compose exec app health-avatar validate
```

Before changing code, read the five documents named at the top of this file, confirm the requested
scope, inspect the latest Git state, and preserve the privacy and identity invariants above.
