import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
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
