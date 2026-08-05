from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccessGrant, ObservationType, Person, SourceSystem, UserAccount
from app.models.enums import AccountStatus, ValueType


@dataclass(frozen=True)
class ObservationTypeSeed:
    code: str
    display_name: str
    default_unit: str
    category: str


OBSERVATION_TYPES = (
    ObservationTypeSeed("body_weight", "Body weight", "lb", "body_composition"),
    ObservationTypeSeed("resting_heart_rate", "Resting heart rate", "bpm", "cardiovascular"),
    ObservationTypeSeed("sleep_duration", "Sleep duration", "hour", "sleep"),
    ObservationTypeSeed("step_count", "Step count", "count", "activity"),
    ObservationTypeSeed(
        "systolic_blood_pressure", "Systolic blood pressure", "mmHg", "cardiovascular"
    ),
    ObservationTypeSeed(
        "diastolic_blood_pressure", "Diastolic blood pressure", "mmHg", "cardiovascular"
    ),
)


def seed_development(session: Session) -> dict[str, int]:
    """Idempotently seed the controlled development catalog and synthetic demo identity."""
    created_types = 0
    for seed in OBSERVATION_TYPES:
        existing = session.scalar(select(ObservationType).where(ObservationType.code == seed.code))
        if existing is None:
            session.add(
                ObservationType(
                    code=seed.code,
                    display_name=seed.display_name,
                    description=f"Canonical {seed.display_name.lower()} observation.",
                    default_unit=seed.default_unit,
                    value_type=ValueType.NUMERIC,
                    category=seed.category,
                    active=True,
                )
            )
            created_types += 1

    person_created = 0
    if session.scalar(select(Person).where(Person.external_reference == "kevin-demo")) is None:
        session.add(
            Person(
                external_reference="kevin-demo",
                preferred_name="Kevin Demo",
                timezone="America/New_York",
            )
        )
        person_created = 1

    source_created = 0
    if session.scalar(select(SourceSystem).where(SourceSystem.name == "manual-csv")) is None:
        session.add(
            SourceSystem(
                name="manual-csv",
                source_type="csv_import",
                vendor="Health Avatar",
                description="Synthetic development canonical CSV source.",
            )
        )
        source_created = 1
    session.flush()

    identities = (
        ("dev-owner", "owner@example.invalid", "Kevin Demo Owner", True, False),
        ("dev-viewer", "viewer@example.invalid", "Andrea Demo Viewer", True, False),
        ("dev-pending", "pending@example.invalid", "Pending Demo User", False, False),
        ("dev-admin", "admin@example.invalid", "Administrator Demo", True, True),
        ("dev-caregiver", "caregiver@example.invalid", "Caregiver Demo", True, False),
    )
    users_created = 0
    accounts: dict[str, UserAccount] = {}
    for subject, email, name, active, administrator in identities:
        account = session.scalar(
            select(UserAccount).where(
                UserAccount.auth_provider == "development",
                UserAccount.provider_subject == subject,
            )
        )
        if account is None:
            account = UserAccount(
                auth_provider="development",
                provider_subject=subject,
                email=email,
                email_verified=True,
                display_name=name,
                account_status=AccountStatus.ACTIVE if active else AccountStatus.PENDING,
                is_active=active,
                is_system_administrator=administrator,
            )
            session.add(account)
            users_created += 1
        accounts[subject] = account
    session.flush()
    person = session.scalar(select(Person).where(Person.external_reference == "kevin-demo"))
    assert person is not None
    grants_created = 0
    grant_specs = (
        ("dev-owner", "owner", True, False),
        ("dev-viewer", "viewer", False, False),
        ("dev-caregiver", "caregiver", True, False),
        ("dev-pending", "viewer", False, True),
    )
    for subject, role, can_approve, revoked in grant_specs:
        existing_grant = session.scalar(
            select(AccessGrant).where(
                AccessGrant.user_account_id == accounts[subject].id,
                AccessGrant.person_id == person.id,
                AccessGrant.role == role,
            )
        )
        if existing_grant is None:
            session.add(
                AccessGrant(
                    user_account_id=accounts[subject].id,
                    person_id=person.id,
                    role=role,
                    can_approve=can_approve,
                    revoked_at=datetime.now(UTC) if revoked else None,
                    granted_by_user_account_id=accounts["dev-admin"].id,
                    revoked_by_user_account_id=accounts["dev-admin"].id if revoked else None,
                )
            )
            grants_created += 1
    session.commit()
    return {
        "observation_types_created": created_types,
        "persons_created": person_created,
        "source_systems_created": source_created,
        "user_accounts_created": users_created,
        "access_grants_created": grants_created,
    }
