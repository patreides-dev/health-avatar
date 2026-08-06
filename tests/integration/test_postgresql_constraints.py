import os
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
def test_postgresql_is_reachable_when_configured() -> None:
    url = os.getenv("HEALTH_AVATAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set HEALTH_AVATAR_TEST_DATABASE_URL for PostgreSQL integration checks")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT current_setting('server_version_num')::int")) >= 160000
        )


@pytest.mark.integration
def test_postgresql_rejects_invalid_device_assignment() -> None:
    url = os.getenv("HEALTH_AVATAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set HEALTH_AVATAR_TEST_DATABASE_URL for PostgreSQL integration checks")
    engine = create_engine(url)
    person_id, device_id, assignment_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text(
                "INSERT INTO persons (id, preferred_name, timezone, status) "
                "VALUES (:id, 'Constraint Test', 'UTC', 'active')"
            ),
            {"id": person_id},
        )
        connection.execute(
            text(
                "INSERT INTO devices (id, manufacturer, model, device_type) "
                "VALUES (:id, 'Synthetic', 'Test', 'test')"
            ),
            {"id": device_id},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO person_device_assignments "
                    "(id, person_id, device_id, assigned_from, assigned_until, assignment_type) "
                    "VALUES (:id, :person_id, :device_id, :start, :end, 'test')"
                ),
                {
                    "id": assignment_id,
                    "person_id": person_id,
                    "device_id": device_id,
                    "start": now,
                    "end": now - timedelta(days=1),
                },
            )
        transaction.rollback()


@pytest.mark.integration
def test_populated_version_01_database_upgrades_and_downgrades() -> None:
    url_text = os.getenv("HEALTH_AVATAR_TEST_DATABASE_URL")
    if not url_text:
        pytest.skip("Set HEALTH_AVATAR_TEST_DATABASE_URL for PostgreSQL integration checks")
    base_url = make_url(url_text)
    database_name = f"health_avatar_migration_{uuid4().hex}"
    admin_url = base_url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    test_url = base_url.set(database=database_name)
    environment = dict(os.environ)
    environment["HEALTH_AVATAR_DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        subprocess.run(["alembic", "upgrade", "20260804_0001"], check=True, env=environment)
        test_engine = create_engine(test_url)
        person_id = uuid4()
        with test_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO persons (id, preferred_name, timezone, status) "
                    "VALUES (:id, 'Synthetic Migration Person', 'UTC', 'active')"
                ),
                {"id": person_id},
            )
        subprocess.run(["alembic", "upgrade", "head"], check=True, env=environment)
        with test_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM persons WHERE id = :id"), {"id": person_id}
                )
                == 1
            )
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260805_0003"
            )
            assert connection.scalar(text("SELECT to_regclass('public.source_artifacts')")) == (
                "source_artifacts"
            )
        subprocess.run(["alembic", "downgrade", "20260804_0001"], check=True, env=environment)
        with test_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM persons WHERE id = :id"), {"id": person_id}
                )
                == 1
            )
        subprocess.run(["alembic", "upgrade", "head"], check=True, env=environment)
        with test_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260805_0003"
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM persons WHERE id = :id"), {"id": person_id}
                )
                == 1
            )
        test_engine.dispose()
    finally:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{database_name}'"
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin_engine.dispose()
