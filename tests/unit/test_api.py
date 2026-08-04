from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.canonical_csv import import_canonical_csv
from app.models import Person, SourceSystem


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def test_person_api_creation(client: TestClient) -> None:
    response = client.post(
        "/api/v1/persons",
        json={
            "external_reference": "api-person",
            "preferred_name": "API Person",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201
    assert response.json()["external_reference"] == "api-person"


def test_structured_validation_error(client: TestClient) -> None:
    response = client.post("/api/v1/persons", json={"preferred_name": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_observation_api_filtering(client: TestClient, seeded_session: Session) -> None:
    person = seeded_session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    source = seeded_session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv"))
    assert person is not None and source is not None
    content = (
        b"person_external_reference,observation_type,observed_at,value,unit,measurement_method,reliability_classification,source_record_identifier\n"
        b"kevin-demo,body_weight,2026-08-01T07:15:00-04:00,238.4,lb,measured,consumer_device,w-1\n"
        b"kevin-demo,step_count,2026-08-02T07:15:00-04:00,100,count,measured,consumer_device,s-1\n"
    )
    import_canonical_csv(seeded_session, content=content, filename="api.csv", source_system=source)
    response = client.get(
        f"/api/v1/persons/{person.id}/observations",
        params={"observation_type": "body_weight", "observed_from": "2026-08-01T00:00:00-04:00"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["observation_type"]["code"] == "body_weight"
