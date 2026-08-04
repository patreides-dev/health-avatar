# Health Avatar

Health Avatar is a privacy-first, person-agnostic platform for longitudinal health data. Version
0.1 is a backend foundation: it models people as immutable UUID identities, records provenance,
imports a strict canonical CSV, and exposes a FastAPI API. It does not diagnose conditions or offer
treatment recommendations.

## Current status and architecture

The application uses Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL 16, Typer,
Pytest, Ruff, MyPy, and Docker Compose. HTTP and CLI adapters call the same service layer. Raw
rejected rows are retained in `import_errors`; accepted values are normalized into typed
`health_observations`. A derived-data layer is reserved for later versions. See
[`docs/architecture.md`](docs/architecture.md) and [`docs/data-model.md`](docs/data-model.md).

## Docker Compose setup

Requirements: Docker with Compose v2.

```sh
cp .env.example .env
docker compose up --build -d
docker compose exec app health-avatar seed development
docker compose exec app health-avatar validate
```

The app starts at <http://localhost:8000>, generated documentation at `/docs`, and health status at
`/health`. The app container runs `alembic upgrade head` before serving. Stop with
`docker compose down`; add `-v` only when intentionally deleting the development database.

## Local development

Use Python 3.12 and a PostgreSQL URL reachable from the host:

```sh
python -m venv .venv
.venv/Scripts/activate              # Windows
python -m pip install -e ".[dev]"
copy .env.example .env              # Windows; then change db host from db to localhost
alembic upgrade head
health-avatar seed development
pytest
ruff format --check .
ruff check .
mypy app
pre-commit install
```

Create a migration with `alembic revision --autogenerate -m "description"`, review it, then run
`alembic upgrade head`. Downgrade the initial schema with `alembic downgrade base` only on a database
whose data may be destroyed.

## CLI examples

```sh
health-avatar db upgrade
health-avatar seed development
health-avatar import csv --person-external-reference kevin-demo --source-system manual-csv data/examples/canonical-observations.csv
health-avatar validate
```

The development seed is idempotent and is the only place the synthetic `kevin-demo` identity is
created. Migrations contain no person records.

## API examples

```sh
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/v1/persons \
  -H "Content-Type: application/json" \
  -d '{"external_reference":"person-001","preferred_name":"Sample Person","timezone":"UTC"}'
curl "http://localhost:8000/api/v1/persons/PERSON_UUID/observations?observation_type=body_weight&limit=50&offset=0"
curl -X POST http://localhost:8000/api/v1/imports/csv \
  -F source_system_id=SOURCE_UUID -F person_external_reference=kevin-demo \
  -F file=@data/examples/canonical-observations.csv
```

## Privacy warning and Version 0.1 limitations

Never use the tracked sample path for real exports or commit real health data. Version 0.1 has no
authentication or authorization enforcement, encryption-at-rest orchestration, frontend, unit
conversion, advanced deduplication, derived analytics, wearable connector, or document extraction.
Its duplicate key depends on a trustworthy source record identifier and may treat corrected source
records as duplicates. It is suitable only for private development environments, not public use.

