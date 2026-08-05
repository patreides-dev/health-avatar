import hashlib
from collections.abc import Callable
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Person, SourceArtifact, SourceSystem


def identifiers(session: Session) -> tuple[str, str]:
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    source = session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv"))
    assert person is not None and source is not None
    return str(person.id), str(source.id)


def test_safe_upload_creates_hashed_artifact_without_storage_details(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    person_id, source_id = identifiers(seeded_session)
    content = b"synthetic,csv\n"
    response = client.post(
        "/api/v1/artifacts",
        data={"person_id": person_id, "source_system_id": source_id},
        files={"file": ("../../private.csv", content, "text/csv")},
        headers=login("dev-owner"),
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["original_filename"] == "private.csv"
    assert payload["file_sha256"] == hashlib.sha256(content).hexdigest()
    assert "storage_key" not in payload and "storage_backend" not in payload
    artifact = seeded_session.get(SourceArtifact, UUID(payload["id"]))
    assert artifact is not None and artifact.storage_key is not None
    assert "private.csv" not in artifact.storage_key and ".." not in artifact.storage_key


def test_upload_limits_types_and_authorization(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    person_id, source_id = identifiers(seeded_session)
    headers = login("dev-owner")
    oversized = client.post(
        "/api/v1/artifacts",
        data={"person_id": person_id, "source_system_id": source_id},
        files={"file": ("large.csv", b"x" * 2049, "text/csv")},
        headers=headers,
    )
    assert oversized.status_code == 422
    unsupported = client.post(
        "/api/v1/artifacts",
        data={"person_id": person_id, "source_system_id": source_id},
        files={"file": ("image.png", b"png", "image/png")},
        headers=headers,
    )
    assert unsupported.status_code == 422
    viewer = login("dev-viewer")
    forbidden = client.post(
        "/api/v1/artifacts",
        data={"person_id": person_id, "source_system_id": source_id},
        files={"file": ("safe.csv", b"x", "text/csv")},
        headers=viewer,
    )
    assert forbidden.status_code == 404
