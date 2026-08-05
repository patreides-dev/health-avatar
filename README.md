# Health Avatar

Health Avatar is a privacy-first, person-agnostic platform for longitudinal health data. Version
0.2A adds secure identity, person-level authorization, immutable source artifacts, staged adapter
processing, human review, and provenance-preserving promotion. It does not diagnose, recommend
treatment, or perform production AI extraction.

## Local development

Use Docker Compose v2:

```powershell
Copy-Item .env.example .env
# Set HEALTH_AVATAR_DEVELOPMENT_AUTH_ENABLED=true only for local synthetic use.
docker compose up --build -d
docker compose exec app health-avatar db upgrade
docker compose exec app health-avatar seed development
docker compose exec app health-avatar validate
```

Open <http://localhost:8000>. Google login requires the configuration documented in
[`docs/authentication.md`](docs/authentication.md). Development login is visibly marked and uses
only deterministic synthetic identities. It is disabled by default and forbidden in production.

The seed creates six observation types, synthetic `kevin-demo`, `manual-csv`, and synthetic owner,
viewer, caregiver, pending, administrator, and revoked-grant examples. Migrations never create a
person or account.

## CLI examples

Commands that change security or health data require an explicit actor UUID:

```powershell
health-avatar users list --actor-user ADMIN_UUID
health-avatar users activate USER_UUID --actor-user ADMIN_UUID
health-avatar access grant --user USER_UUID --person PERSON_UUID --role viewer --actor-user ADMIN_UUID
health-avatar import csv data/examples/canonical-observations.csv `
  --person-external-reference kevin-demo --source-system manual-csv --actor-user OWNER_UUID
health-avatar processing show RUN_UUID --actor-user OWNER_UUID
health-avatar candidates approve CANDIDATE_UUID --actor-user OWNER_UUID
```

The CLI is a trusted local administrative adapter, not a hidden superuser. The supplied actor is
looked up, must be active, and is authorized by the same services as HTTP routes.

## API and interface

JSON APIs are under `/api/v1`; OpenAPI is at `/docs`. Browser state-changing requests use the
session-bound CSRF token. Version 0.1 route paths are retained but now require authentication and
authorization. Unauthorized object IDs normally return the same 404 as nonexistent objects.

The responsive server-rendered interface provides login, pending-account, person selector, person
summary, artifact upload, processing-run, and candidate review pages. It intentionally has no
analytics dashboard.

## Privacy warning

Never commit real health data, artifacts, exports, credentials, `.env`, database dumps, or backups.
Local artifact bytes live outside relational columns in a configured storage directory. Version
0.2A has not undergone a public-deployment review, does not include malware scanning or encrypted
cloud storage, and makes no HIPAA or regulatory-compliance claim. See [`SECURITY.md`](SECURITY.md)
and [`docs/threat-model.md`](docs/threat-model.md).
