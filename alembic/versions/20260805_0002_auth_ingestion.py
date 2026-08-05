"""Add secure identity and universal ingestion foundation.

Revision ID: 20260805_0002
Revises: 20260804_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260805_0002"
down_revision: str | None = "20260804_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
UUID = sa.Uuid()
TZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # Version 0.1 rendered already-conventional check names through the naming
    # convention a second time. Normalize names without changing their rules.
    for table, old_name, new_name in (
        (
            "access_grants",
            "ck_access_grants_ck_access_grants_valid_period",
            "ck_access_grants_valid_period",
        ),
        (
            "household_memberships",
            "ck_household_memberships_ck_household_memberships_valid_period",
            "ck_household_memberships_valid_period",
        ),
        (
            "person_device_assignments",
            "ck_person_device_assignments_ck_person_device_assignmen_5f2f",
            "ck_person_device_assignments_valid_period",
        ),
        (
            "import_batches",
            "ck_import_batches_ck_import_batches_nonnegative_accepted",
            "ck_import_batches_nonnegative_accepted",
        ),
        (
            "import_batches",
            "ck_import_batches_ck_import_batches_nonnegative_rejected",
            "ck_import_batches_nonnegative_rejected",
        ),
        (
            "import_batches",
            "ck_import_batches_ck_import_batches_nonnegative_total",
            "ck_import_batches_nonnegative_total",
        ),
        (
            "health_observations",
            "ck_health_observations_ck_health_observations_exactly_o_7cde",
            "ck_health_observations_exactly_one_typed_value",
        ),
        (
            "health_observations",
            "ck_health_observations_ck_health_observations_valid_period",
            "ck_health_observations_valid_period",
        ),
    ):
        op.execute(sa.text(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"'))

    op.drop_constraint("uq_user_accounts_email", "user_accounts", type_="unique")
    op.add_column("user_accounts", sa.Column("auth_provider", sa.String(50)))
    op.add_column("user_accounts", sa.Column("provider_subject", sa.String(255)))
    op.add_column(
        "user_accounts",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("user_accounts", sa.Column("profile_image_url", sa.String(1000)))
    op.add_column(
        "user_accounts",
        sa.Column("account_status", sa.String(32), server_default="active", nullable=False),
    )
    op.add_column(
        "user_accounts",
        sa.Column(
            "is_system_administrator", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column("user_accounts", sa.Column("last_login_at", TZ))
    op.create_unique_constraint(
        "uq_user_provider_subject", "user_accounts", ["auth_provider", "provider_subject"]
    )
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"])

    op.add_column("access_grants", sa.Column("expires_at", TZ))
    op.create_check_constraint(
        op.f("ck_access_grants_valid_expiry"),
        "access_grants",
        "expires_at IS NULL OR expires_at >= granted_at",
    )
    op.add_column(
        "access_grants",
        sa.Column("can_approve", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("access_grants", sa.Column("granted_by_user_account_id", UUID))
    op.add_column("access_grants", sa.Column("revoked_by_user_account_id", UUID))
    op.create_foreign_key(
        "fk_access_grants_granted_by_user_account_id_user_accounts",
        "access_grants",
        "user_accounts",
        ["granted_by_user_account_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_access_grants_revoked_by_user_account_id_user_accounts",
        "access_grants",
        "user_accounts",
        ["revoked_by_user_account_id"],
        ["id"],
    )
    op.create_index(
        "ix_access_grants_user_person_active",
        "access_grants",
        ["user_account_id", "person_id", "revoked_at", "expires_at"],
    )

    op.create_table(
        "app_sessions",
        sa.Column("user_account_id", UUID, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("invalidated_at", TZ),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name="fk_app_sessions_user_account_id_user_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_app_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_app_sessions_token_hash"),
    )
    op.create_index("ix_app_sessions_user_account_id", "app_sessions", ["user_account_id"])
    op.create_index("ix_app_sessions_expires_at", "app_sessions", ["expires_at"])

    op.create_table(
        "source_artifacts",
        sa.Column("subject_person_id", UUID),
        sa.Column("source_system_id", UUID),
        sa.Column("submitted_by_user_account_id", UUID, nullable=False),
        sa.Column("parent_artifact_id", UUID),
        sa.Column("artifact_kind", sa.String(100), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(500)),
        sa.Column("original_external_reference", sa.String(1000)),
        sa.Column("file_sha256", sa.String(64)),
        sa.Column("content_length", sa.Integer()),
        sa.Column("storage_backend", sa.String(100), nullable=False),
        sa.Column("storage_key", sa.String(500)),
        sa.Column("idempotency_scope", sa.String(64), nullable=False),
        sa.Column("captured_at", TZ),
        sa.Column("received_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("processing_status", sa.String(50), nullable=False),
        sa.Column("sensitivity_classification", sa.String(100), nullable=False),
        sa.Column("metadata_json", JSONB, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_person_id"],
            ["persons.id"],
            name="fk_source_artifacts_subject_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name="fk_source_artifacts_source_system_id_source_systems",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_account_id"],
            ["user_accounts.id"],
            name="fk_source_artifacts_submitted_by_user_account_id_user_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["parent_artifact_id"],
            ["source_artifacts.id"],
            name="fk_source_artifacts_parent_artifact_id_source_artifacts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_artifacts"),
        sa.UniqueConstraint("storage_key", name="uq_source_artifacts_storage_key"),
        sa.UniqueConstraint("idempotency_scope", name="uq_source_artifacts_idempotency_scope"),
    )
    op.create_index(
        "ix_source_artifacts_person_received",
        "source_artifacts",
        ["subject_person_id", "received_at"],
    )

    op.create_table(
        "processing_runs",
        sa.Column("source_artifact_id", UUID, nullable=False),
        sa.Column("adapter_name", sa.String(255), nullable=False),
        sa.Column("adapter_version", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("requested_by_user_account_id", UUID, nullable=False),
        sa.Column("started_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", TZ),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("review_required_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text()),
        sa.Column("configuration_json", JSONB, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["source_artifacts.id"],
            name="fk_processing_runs_source_artifact_id_source_artifacts",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_account_id"],
            ["user_accounts.id"],
            name="fk_processing_runs_requested_by_user_account_id_user_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_processing_runs"),
        sa.UniqueConstraint(
            "source_artifact_id", "adapter_name", "schema_version", name="uq_processing_scope"
        ),
    )
    op.create_index(
        "ix_processing_runs_artifact_status", "processing_runs", ["source_artifact_id", "status"]
    )

    op.create_table(
        "candidate_records",
        sa.Column("processing_run_id", UUID, nullable=False),
        sa.Column("subject_person_id", UUID),
        sa.Column("candidate_type", sa.String(100), nullable=False),
        sa.Column("source_locator", sa.String(500), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("raw_candidate_json", JSONB, nullable=False),
        sa.Column("normalized_candidate_json", JSONB),
        sa.Column("approved_by_user_account_id", UUID),
        sa.Column("approved_at", TZ),
        sa.Column("rejected_by_user_account_id", UUID),
        sa.Column("rejected_at", TZ),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_candidate_records_processing_run_id_processing_runs",
        ),
        sa.ForeignKeyConstraint(
            ["subject_person_id"],
            ["persons.id"],
            name="fk_candidate_records_subject_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_account_id"],
            ["user_accounts.id"],
            name="fk_candidate_records_approved_by_user_account_id_user_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by_user_account_id"],
            ["user_accounts.id"],
            name="fk_candidate_records_rejected_by_user_account_id_user_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_candidate_records"),
    )
    op.create_index(
        "ix_candidate_records_run_status", "candidate_records", ["processing_run_id", "status"]
    )

    op.create_table(
        "validation_issues",
        sa.Column("processing_run_id", UUID, nullable=False),
        sa.Column("candidate_record_id", UUID),
        sa.Column("field_name", sa.String(255)),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("issue_code", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_locator", sa.String(500)),
        sa.Column("details_json", JSONB, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_run_id"],
            ["processing_runs.id"],
            name="fk_validation_issues_processing_run_id_processing_runs",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_record_id"],
            ["candidate_records.id"],
            name="fk_validation_issues_candidate_record_id_candidate_records",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_validation_issues"),
    )
    op.create_index(
        "ix_validation_issues_processing_run_id", "validation_issues", ["processing_run_id"]
    )

    op.create_table(
        "audit_events",
        sa.Column("actor_user_account_id", UUID, nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(100), nullable=False),
        sa.Column("target_id", UUID, nullable=False),
        sa.Column("details_json", JSONB, nullable=False),
        sa.Column("occurred_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_account_id"],
            ["user_accounts.id"],
            name="fk_audit_events_actor_user_account_id_user_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_actor_user_account_id", "audit_events", ["actor_user_account_id"]
    )
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_target_id", "audit_events", ["target_id"])

    op.add_column("import_batches", sa.Column("source_artifact_id", UUID))
    op.add_column("import_batches", sa.Column("processing_run_id", UUID))
    op.drop_constraint("uq_import_batch_file", "import_batches", type_="unique")
    op.create_index(
        "ix_import_batches_file_scope",
        "import_batches",
        ["source_system_id", "file_sha256", "subject_person_id"],
    )
    op.create_foreign_key(
        "fk_import_batches_source_artifact_id_source_artifacts",
        "import_batches",
        "source_artifacts",
        ["source_artifact_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_import_batches_processing_run_id_processing_runs",
        "import_batches",
        "processing_runs",
        ["processing_run_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_import_batches_processing_run_id", "import_batches", ["processing_run_id"]
    )

    for name, table, constraint_name in (
        ("source_artifact_id", "source_artifacts", "fk_health_obs_source_artifact"),
        ("processing_run_id", "processing_runs", "fk_health_obs_processing_run"),
        ("candidate_record_id", "candidate_records", "fk_health_obs_candidate"),
        ("created_by_user_account_id", "user_accounts", "fk_health_obs_creator"),
        ("approved_by_user_account_id", "user_accounts", "fk_health_obs_approver"),
    ):
        op.add_column("health_observations", sa.Column(name, UUID))
        op.create_foreign_key(constraint_name, "health_observations", table, [name], ["id"])
    op.add_column("health_observations", sa.Column("adapter_name", sa.String(255)))
    op.add_column("health_observations", sa.Column("adapter_version", sa.String(50)))
    op.create_unique_constraint(
        "uq_health_observations_candidate_record_id", "health_observations", ["candidate_record_id"]
    )
    op.create_index(
        "ix_health_observations_person_type_time",
        "health_observations",
        ["person_id", "observation_type_id", "observed_at"],
    )
    op.create_index(
        "ix_health_observations_provenance",
        "health_observations",
        ["source_artifact_id", "processing_run_id", "candidate_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_health_observations_provenance", table_name="health_observations")
    op.drop_index("ix_health_observations_person_type_time", table_name="health_observations")
    op.drop_constraint(
        "uq_health_observations_candidate_record_id", "health_observations", type_="unique"
    )
    for name, _table, constraint_name in reversed(
        (
            ("source_artifact_id", "source_artifacts", "fk_health_obs_source_artifact"),
            ("processing_run_id", "processing_runs", "fk_health_obs_processing_run"),
            ("candidate_record_id", "candidate_records", "fk_health_obs_candidate"),
            ("created_by_user_account_id", "user_accounts", "fk_health_obs_creator"),
            ("approved_by_user_account_id", "user_accounts", "fk_health_obs_approver"),
        )
    ):
        op.drop_constraint(constraint_name, "health_observations", type_="foreignkey")
        op.drop_column("health_observations", name)
    op.drop_column("health_observations", "adapter_version")
    op.drop_column("health_observations", "adapter_name")
    op.drop_constraint("uq_import_batches_processing_run_id", "import_batches", type_="unique")
    op.drop_index("ix_import_batches_file_scope", table_name="import_batches")
    op.create_unique_constraint(
        "uq_import_batch_file",
        "import_batches",
        ["source_system_id", "file_sha256", "subject_person_id"],
    )
    op.drop_constraint(
        "fk_import_batches_processing_run_id_processing_runs", "import_batches", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_import_batches_source_artifact_id_source_artifacts",
        "import_batches",
        type_="foreignkey",
    )
    op.drop_column("import_batches", "processing_run_id")
    op.drop_column("import_batches", "source_artifact_id")
    op.drop_table("audit_events")
    op.drop_table("validation_issues")
    op.drop_table("candidate_records")
    op.drop_table("processing_runs")
    op.drop_table("source_artifacts")
    op.drop_table("app_sessions")
    op.drop_index("ix_access_grants_user_person_active", table_name="access_grants")
    op.drop_constraint(op.f("ck_access_grants_valid_expiry"), "access_grants", type_="check")
    op.drop_constraint(
        "fk_access_grants_revoked_by_user_account_id_user_accounts",
        "access_grants",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_access_grants_granted_by_user_account_id_user_accounts",
        "access_grants",
        type_="foreignkey",
    )
    for column in (
        "revoked_by_user_account_id",
        "granted_by_user_account_id",
        "can_approve",
        "expires_at",
    ):
        op.drop_column("access_grants", column)
    op.drop_index("ix_user_accounts_email", table_name="user_accounts")
    op.drop_constraint("uq_user_provider_subject", "user_accounts", type_="unique")
    for column in (
        "last_login_at",
        "is_system_administrator",
        "account_status",
        "profile_image_url",
        "email_verified",
        "provider_subject",
        "auth_provider",
    ):
        op.drop_column("user_accounts", column)
    op.create_unique_constraint("uq_user_accounts_email", "user_accounts", ["email"])
    for table, current_name, old_name in (
        (
            "access_grants",
            "ck_access_grants_valid_period",
            "ck_access_grants_ck_access_grants_valid_period",
        ),
        (
            "household_memberships",
            "ck_household_memberships_valid_period",
            "ck_household_memberships_ck_household_memberships_valid_period",
        ),
        (
            "person_device_assignments",
            "ck_person_device_assignments_valid_period",
            "ck_person_device_assignments_ck_person_device_assignmen_5f2f",
        ),
        (
            "import_batches",
            "ck_import_batches_nonnegative_accepted",
            "ck_import_batches_ck_import_batches_nonnegative_accepted",
        ),
        (
            "import_batches",
            "ck_import_batches_nonnegative_rejected",
            "ck_import_batches_ck_import_batches_nonnegative_rejected",
        ),
        (
            "import_batches",
            "ck_import_batches_nonnegative_total",
            "ck_import_batches_ck_import_batches_nonnegative_total",
        ),
        (
            "health_observations",
            "ck_health_observations_exactly_one_typed_value",
            "ck_health_observations_ck_health_observations_exactly_o_7cde",
        ),
        (
            "health_observations",
            "ck_health_observations_valid_period",
            "ck_health_observations_ck_health_observations_valid_period",
        ),
    ):
        op.execute(
            sa.text(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{current_name}" TO "{old_name}"')
        )
