from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Person


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.2.0"}


def test_anonymous_health_data_is_blocked(client: TestClient, seeded_session: Session) -> None:
    person = seeded_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    assert person is not None
    assert client.get("/api/v1/persons").status_code == 401
    assert client.get(f"/api/v1/persons/{person.id}").status_code == 401
    assert client.get(f"/api/v1/persons/{person.id}/observations").status_code == 401


def test_admin_person_creation_requires_csrf(
    client: TestClient, login: Callable[[str], dict[str, str]]
) -> None:
    headers = login("dev-admin")
    payload = {
        "external_reference": "api-person",
        "preferred_name": "API Person",
        "timezone": "UTC",
    }
    assert client.post("/api/v1/persons", json=payload).status_code == 403
    response = client.post("/api/v1/persons", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["external_reference"] == "api-person"


def test_structured_validation_error_after_security_checks(
    client: TestClient, login: Callable[[str], dict[str, str]]
) -> None:
    response = client.post(
        "/api/v1/persons", json={"preferred_name": ""}, headers=login("dev-admin")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_person_selector_and_resource_hiding(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    allowed = seeded_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    hidden = Person(external_reference="hidden", preferred_name="Hidden Person", timezone="UTC")
    seeded_session.add(hidden)
    seeded_session.commit()
    login("dev-viewer")
    response = client.get("/api/v1/persons")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(allowed.id)]
    assert client.get(f"/api/v1/persons/{hidden.id}").status_code == 404
    assert client.get(f"/api/v1/persons/{hidden.id}/observations").status_code == 404


def test_viewer_cannot_create_or_upload(
    client: TestClient, seeded_session: Session, login: Callable[[str], dict[str, str]]
) -> None:
    person = seeded_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    headers = login("dev-viewer")
    response = client.post(
        "/api/v1/persons", json={"preferred_name": "No", "timezone": "UTC"}, headers=headers
    )
    assert response.status_code == 403
    assert person is not None
    response = client.post(
        "/api/v1/imports/csv",
        data={
            "source_system_id": "00000000-0000-0000-0000-000000000000",
            "person_external_reference": "kevin-demo",
        },
        files={"file": ("test.csv", b"x", "text/csv")},
        headers=headers,
    )
    assert response.status_code == 404


def test_anonymous_browser_redirects_and_pending_sees_no_data(
    client: TestClient, login: Callable[[str], dict[str, str]]
) -> None:
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/auth/login"
    login("dev-pending")
    response = client.get("/app", follow_redirects=False)
    assert response.headers["location"] == "/pending"
    pending = client.get("/pending")
    assert pending.status_code == 200
    assert "Access pending" in pending.text
    assert "Kevin Demo" not in pending.text
