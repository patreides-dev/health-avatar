import io
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.contracts import HealthExtractionRequest, HealthExtractionResponse
from app.ai.providers import (
    MockExtractionProvider,
    OpenAIExtractionProvider,
    ProviderError,
    ProviderTimeout,
    provider_for,
)
from app.ai.registry import HealthFactDefinition, HealthFactRegistry, registry
from app.core.config import Settings
from app.models import (
    AIIntakeRequest,
    AIProcessingConsent,
    CandidateRecord,
    ExerciseMetric,
    ExerciseSession,
    HealthObservation,
    Person,
    ProposedFactRevision,
    ProposedHealthFact,
    ProposedHealthFactGroup,
    UserAccount,
    ValidationIssue,
)
from app.services.image_safety import UnsafeImageError, create_safe_derivative


def request(text: str, modality: str = "text") -> HealthExtractionRequest:
    return HealthExtractionRequest(modality=modality, purpose="general_health", user_text=text)


def test_mock_provider_extracts_general_groups_and_labs() -> None:
    provider = MockExtractionProvider()
    response = provider.extract_health_facts(
        request(
            "I weighed 231.4 pounds. Blood pressure was 128 over 79. "
            "Total cholesterol 184, LDL 112, HDL 47, and triglycerides 126."
        )
    )
    assert {fact.fact_code for fact in response.proposed_health_facts} == {
        "body_weight",
        "blood_pressure_systolic",
        "blood_pressure_diastolic",
        "total_cholesterol",
        "ldl_cholesterol",
        "hdl_cholesterol",
        "triglycerides",
    }
    assert {group.group_type for group in response.detected_fact_groups} == {
        "blood_pressure_reading",
        "laboratory_panel",
    }
    assert all(fact.interpretation_notes is None for fact in response.proposed_health_facts)


def test_mock_provider_partial_unknown_and_failures() -> None:
    partial = MockExtractionProvider().extract_health_facts(
        request("Something unknown [mock:partial]")
    )
    assert partial.proposed_health_facts[0].fact_code == "unmapped_health_fact"
    assert partial.warnings
    with pytest.raises(ProviderTimeout):
        MockExtractionProvider().extract_health_facts(request("[mock:timeout]"))
    with pytest.raises(ProviderError):
        MockExtractionProvider().extract_health_facts(request("[mock:error]"))
    with pytest.raises(ProviderError):
        MockExtractionProvider().extract_health_facts(request("[mock:malformed]"))


def test_fact_registry_is_extensible() -> None:
    assert registry.get("body_weight").canonical_target == "health_observation"  # type: ignore[union-attr]
    assert registry.get("ldl_cholesterol").canonical_target is None  # type: ignore[union-attr]
    assert registry.get("unknown") is None
    custom = HealthFactRegistry()
    definition = HealthFactDefinition(
        "custom", "Custom", "other", "numeric", frozenset({"count"}), None
    )
    custom.register(definition)
    assert custom.all() == (definition,)
    with pytest.raises(ValueError):
        custom.register(definition)


def _png(width: int = 20, height: int = 10) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def test_image_safety_reencodes_and_rejects_invalid(test_settings: Settings) -> None:
    safe = create_safe_derivative(_png(), "image/png", test_settings)
    assert (safe.width, safe.height, safe.media_type) == (20, 10, "image/png")
    with pytest.raises(UnsafeImageError, match="Unsupported"):
        create_safe_derivative(_png(), "image/gif", test_settings)
    with pytest.raises(UnsafeImageError, match="corrupt"):
        create_safe_derivative(b"not-an-image", "image/png", test_settings)
    tiny_limit = test_settings.model_copy(update={"max_image_dimension": 5})
    with pytest.raises(UnsafeImageError, match="dimensions"):
        create_safe_derivative(_png(), "image/png", tiny_limit)


def _person(session: Session) -> Person:
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    assert person is not None
    return person


def test_text_intake_review_correction_and_idempotent_promotion(
    client: TestClient,
    seeded_session: Session,
    login: object,
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    created = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={
            "text": "I weighed 231.4 pounds this morning.",
            "purpose": "general_health",
            "sensitivity": "biometric",
            "consent": True,
        },
    )
    assert created.status_code == 201, created.text
    intake_id = created.json()["id"]
    facts = client.get(f"/api/v1/ai-intake/{intake_id}/facts", headers=headers)
    assert facts.status_code == 200
    fact = facts.json()[0]
    assert fact["canonical_status"] == "awaiting_review"
    observed = datetime(2026, 8, 5, 8, tzinfo=UTC).isoformat()
    revised = client.post(
        f"/api/v1/ai-intake/{intake_id}/facts/{fact['id']}/review",
        headers=headers,
        json={"numeric_value": "230.9", "unit": "lb", "observed_at": observed},
    )
    assert revised.status_code == 200
    first = client.post(f"/api/v1/ai-intake/{intake_id}/confirm", headers=headers)
    second = client.post(f"/api/v1/ai-intake/{intake_id}/confirm", headers=headers)
    assert first.status_code == second.status_code == 200
    assert (
        seeded_session.scalar(
            select(HealthObservation).where(HealthObservation.person_id == person.id)
        )
        is not None
    )
    assert len(list(seeded_session.scalars(select(HealthObservation)))) == 1
    assert seeded_session.scalar(select(ProposedFactRevision)) is not None
    assert seeded_session.scalar(select(AIProcessingConsent)) is not None


def test_laboratory_facts_remain_grouped_reviewed_and_noncanonical(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={
            "text": "Total cholesterol 184, LDL 112, HDL 47, triglycerides 126 mg/dL.",
            "purpose": "laboratory",
            "sensitivity": "clinical",
            "consent": True,
        },
    )
    assert response.status_code == 201
    intake_id = response.json()["id"]
    confirmed = client.post(f"/api/v1/ai-intake/{intake_id}/confirm", headers=headers)
    assert confirmed.status_code == 200
    facts = list(seeded_session.scalars(select(ProposedHealthFact)))
    assert len(facts) == 4
    assert {fact.canonical_status for fact in facts} == {"confirmed"}
    assert len(list(seeded_session.scalars(select(ProposedHealthFactGroup)))) == 1
    assert len(list(seeded_session.scalars(select(HealthObservation)))) == 0


def test_reference_range_is_preserved_without_interpretation() -> None:
    response = MockExtractionProvider().extract_health_facts(
        request("LDL 112 reference 0-99 mg/dL")
    )
    fact = response.proposed_health_facts[0]
    assert fact.reference_range_low == 0
    assert fact.reference_range_high == 99
    assert fact.interpretation_notes is None


def test_workout_image_requires_review_then_promotes_exercise(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/image",
        headers=headers,
        data={
            "purpose": "exercise",
            "sensitivity": "exercise",
            "context": "workout elliptical",
            "consent": "true",
        },
        files={"file": ("workout.png", _png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    intake_id = response.json()["id"]
    assert list(seeded_session.scalars(select(ExerciseSession))) == []
    confirmed = client.post(f"/api/v1/ai-intake/{intake_id}/confirm", headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    exercise = seeded_session.scalar(select(ExerciseSession))
    assert exercise is not None
    assert exercise.started_at is None
    assert exercise.duration_seconds == 1800
    assert len(list(seeded_session.scalars(select(ExerciseMetric)))) == 3


def test_viewer_and_missing_consent_cannot_submit(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    person = _person(seeded_session)
    viewer_headers = login("dev-viewer")  # type: ignore[operator]
    denied = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=viewer_headers,
        json={"text": "I weigh 100 lb", "consent": True},
    )
    assert denied.status_code == 404
    owner_headers = login("dev-owner")  # type: ignore[operator]
    no_consent = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=owner_headers,
        json={"text": "I weigh 100 lb", "consent": False},
    )
    assert no_consent.status_code == 422


def test_invalid_fact_blocks_confirmation_and_rejection_is_audited(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={"text": "My weight was 231.4", "consent": True},
    )
    assert response.status_code == 201
    intake_id = response.json()["id"]
    assert client.post(f"/api/v1/ai-intake/{intake_id}/confirm", headers=headers).status_code == 409
    rejected = client.post(
        f"/api/v1/ai-intake/{intake_id}/reject",
        headers=headers,
        json={"reason": "Unit was not available"},
    )
    assert rejected.status_code == 200
    fact = seeded_session.scalar(select(ProposedHealthFact))
    assert fact is not None and fact.canonical_status == "rejected"


def test_reviewer_can_add_supported_fact(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={"text": "Unmapped note", "consent": True},
    )
    intake_id = response.json()["id"]
    added = client.post(
        f"/api/v1/ai-intake/{intake_id}/facts",
        headers=headers,
        json={
            "fact_code": "body_weight",
            "numeric_value": "200",
            "unit": "lb",
            "observed_at": "2026-08-05T08:00:00Z",
            "reason": "Visible but not extracted",
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["source_locator"] == "reviewer_added"


def test_manual_exercise_entry_and_listing(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    created = client.post(
        f"/api/v1/persons/{person.id}/exercise-sessions",
        headers=headers,
        json={
            "exercise_type": "elliptical",
            "duration_seconds": 1200,
            "metrics": [{"code": "distance", "value": "2.5", "unit": "mi"}],
        },
    )
    assert created.status_code == 201, created.text
    listing = client.get(f"/api/v1/persons/{person.id}/exercise-sessions", headers=headers)
    assert listing.status_code == 200 and len(listing.json()) == 1
    fetched = client.get(f"/api/v1/exercise-sessions/{created.json()['id']}", headers=headers)
    assert fetched.status_code == 200


def test_phone_pages_require_auth_and_escape_staged_content(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    person = _person(seeded_session)
    assert (
        client.get(f"/app/persons/{person.id}/add-health", follow_redirects=False).status_code
        == 303
    )
    headers = login("dev-owner")  # type: ignore[operator]
    page = client.get(f"/app/persons/{person.id}/add-health", headers=headers)
    assert page.status_code == 200
    assert "Processing consent" in page.text
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={"text": "<script>alert(1)</script>", "consent": True},
    )
    review = client.get(f"/app/ai-intake/{response.json()['id']}", headers=headers)
    assert review.status_code == 200
    assert "<script>alert(1)</script>" not in review.text


def test_openai_provider_request_mapping_isolated_from_domain() -> None:
    settings = Settings(
        app_env="testing",
        session_secret="synthetic-test-secret-not-for-production",
        ai_provider="openai",
        cloud_ai_enabled=True,
        openai_api_key="synthetic-key",
        openai_model="configured-test-model",
    )
    parsed = HealthExtractionResponse(submission_summary="none")
    client = Mock()
    client.responses.parse.return_value.output_parsed = parsed
    with patch("openai.OpenAI", return_value=client):
        provider = OpenAIExtractionProvider(settings)
        assert provider.extract_health_facts(request("No facts")) is parsed
    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "configured-test-model"
    assert kwargs["store"] is False
    assert "untrusted data" in kwargs["instructions"]
    assert "synthetic-key" not in str(kwargs)
    client.responses.parse.side_effect = TimeoutError()
    with pytest.raises(ProviderTimeout):
        provider.extract_health_facts(request("No facts"))
    client.responses.parse.side_effect = RuntimeError("provider detail must be hidden")
    with pytest.raises(ProviderError, match="request failed"):
        provider.extract_health_facts(request("No facts"))


def test_mock_provider_is_isolated_from_production() -> None:
    settings = Settings(
        app_env="production",
        session_secret="a-production-session-secret-longer-than-32-characters",
        cookie_secure=True,
        google_client_id="synthetic-client",
        ai_provider="mock",
        cloud_ai_enabled=False,
    )
    with pytest.raises(ProviderError, match="development and testing"):
        provider_for(settings)


def test_intake_model_does_not_expose_raw_model_output(
    client: TestClient, seeded_session: Session, login: object
) -> None:
    headers = login("dev-owner")  # type: ignore[operator]
    person = _person(seeded_session)
    response = client.post(
        f"/api/v1/persons/{person.id}/ai-intake/text",
        headers=headers,
        json={"text": "Unmapped health statement", "consent": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert "raw_model_response_json" not in body
    intake = seeded_session.get(AIIntakeRequest, UUID(body["id"]))
    assert intake is not None and intake.raw_model_response_json is not None
    candidate = seeded_session.scalar(select(CandidateRecord))
    assert candidate is not None and candidate.status == "awaiting_review"
    issue = seeded_session.scalar(select(ValidationIssue))
    assert issue is not None and issue.issue_code == "unsupported_fact"
    assert seeded_session.scalar(
        select(UserAccount).where(UserAccount.provider_subject == "dev-owner")
    )
