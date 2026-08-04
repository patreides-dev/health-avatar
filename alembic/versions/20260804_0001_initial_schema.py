"""Create the Version 0.1 multi-person foundation.

Revision ID: 20260804_0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260804_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = sa.Uuid()
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("external_reference", sa.String(255), nullable=True),
        sa.Column("preferred_name", sa.String(255), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_persons"),
        sa.UniqueConstraint("external_reference", name="uq_persons_external_reference"),
    )
    op.create_table(
        "user_accounts",
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
    )
    op.create_table(
        "households",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_households"),
    )
    op.create_table(
        "source_systems",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(100), nullable=False),
        sa.Column("vendor", sa.String(255), nullable=False),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source_systems"),
        sa.UniqueConstraint("name", name="uq_source_systems_name"),
    )
    op.create_table(
        "observation_types",
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("default_unit", sa.String(50), nullable=True),
        sa.Column("value_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_types"),
        sa.UniqueConstraint("code", name="uq_observation_types_code"),
    )
    op.create_table(
        "access_grants",
        sa.Column("user_account_id", UUID, nullable=False),
        sa.Column("person_id", UUID, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("granted_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", TZ, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at", name="ck_access_grants_valid_period"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_access_grants_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name="fk_access_grants_user_account_id_user_accounts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_grants"),
    )
    op.create_table(
        "household_memberships",
        sa.Column("household_id", UUID, nullable=False),
        sa.Column("person_id", UUID, nullable=False),
        sa.Column("joined_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("relationship_label", sa.String(100), nullable=True),
        sa.Column("ended_at", TZ, nullable=True),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= joined_at",
            name="ck_household_memberships_valid_period",
        ),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name="fk_household_memberships_household_id_households",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_household_memberships_person_id_persons"
        ),
        sa.PrimaryKeyConstraint(
            "household_id", "person_id", "joined_at", name="pk_household_memberships"
        ),
    )
    op.create_table(
        "devices",
        sa.Column("source_system_id", UUID, nullable=True),
        sa.Column("manufacturer", sa.String(255), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("device_type", sa.String(100), nullable=False),
        sa.Column("serial_number", sa.String(255), nullable=True),
        sa.Column("external_device_id", sa.String(255), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name="fk_devices_source_system_id_source_systems",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
    )
    op.create_table(
        "person_device_assignments",
        sa.Column("person_id", UUID, nullable=False),
        sa.Column("device_id", UUID, nullable=False),
        sa.Column("assigned_from", TZ, nullable=False),
        sa.Column("assigned_until", TZ, nullable=True),
        sa.Column("assignment_type", sa.String(100), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint(
            "assigned_until IS NULL OR assigned_until > assigned_from",
            name="ck_person_device_assignments_valid_period",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name="fk_person_device_assignments_device_id_devices"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_person_device_assignments_person_id_persons"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_person_device_assignments"),
    )
    op.create_table(
        "import_batches",
        sa.Column("source_system_id", UUID, nullable=False),
        sa.Column("subject_person_id", UUID, nullable=True),
        sa.Column("imported_by_user_account_id", UUID, nullable=True),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("import_started_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("import_completed_at", TZ, nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_rows", sa.Integer(), nullable=False),
        sa.Column("rejected_rows", sa.Integer(), nullable=False),
        sa.Column("importer_name", sa.String(255), nullable=False),
        sa.Column("importer_version", sa.String(50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint("accepted_rows >= 0", name="ck_import_batches_nonnegative_accepted"),
        sa.CheckConstraint("rejected_rows >= 0", name="ck_import_batches_nonnegative_rejected"),
        sa.CheckConstraint("total_rows >= 0", name="ck_import_batches_nonnegative_total"),
        sa.ForeignKeyConstraint(
            ["imported_by_user_account_id"],
            ["user_accounts.id"],
            name="fk_import_batches_imported_by_user_account_id_user_accounts",
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name="fk_import_batches_source_system_id_source_systems",
        ),
        sa.ForeignKeyConstraint(
            ["subject_person_id"],
            ["persons.id"],
            name="fk_import_batches_subject_person_id_persons",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_batches"),
        sa.UniqueConstraint(
            "source_system_id", "file_sha256", "subject_person_id", name="uq_import_batch_file"
        ),
    )
    op.create_table(
        "health_observations",
        sa.Column("person_id", UUID, nullable=False),
        sa.Column("observation_type_id", UUID, nullable=False),
        sa.Column("observed_at", TZ, nullable=False),
        sa.Column("observed_until", TZ, nullable=True),
        sa.Column("numeric_value", sa.Numeric(20, 8), nullable=True),
        sa.Column("text_value", sa.Text(), nullable=True),
        sa.Column("boolean_value", sa.Boolean(), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("source_system_id", UUID, nullable=False),
        sa.Column("device_id", UUID, nullable=True),
        sa.Column("import_batch_id", UUID, nullable=True),
        sa.Column("source_record_identifier", sa.String(500), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("raw_source_row_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("measurement_method", sa.String(32), nullable=False),
        sa.Column("reliability_classification", sa.String(32), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN numeric_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN text_value IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN boolean_value IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_health_observations_exactly_one_typed_value",
        ),
        sa.CheckConstraint(
            "observed_until IS NULL OR observed_until >= observed_at",
            name="ck_health_observations_valid_period",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name="fk_health_observations_device_id_devices"
        ),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_health_observations_import_batch_id_import_batches",
        ),
        sa.ForeignKeyConstraint(
            ["observation_type_id"],
            ["observation_types.id"],
            name="fk_health_observations_observation_type_id_observation_types",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_health_observations_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name="fk_health_observations_source_system_id_source_systems",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_health_observations"),
        sa.UniqueConstraint(
            "source_system_id",
            "source_record_identifier",
            "person_id",
            "observation_type_id",
            name="uq_observation_source_record",
        ),
    )
    op.create_index("ix_health_observations_observed_at", "health_observations", ["observed_at"])
    op.create_index("ix_health_observations_person_id", "health_observations", ["person_id"])
    op.create_table(
        "import_errors",
        sa.Column("import_batch_id", UUID, nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_row_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batches.id"],
            name="fk_import_errors_import_batch_id_import_batches",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_import_errors"),
    )


def downgrade() -> None:
    op.drop_table("import_errors")
    op.drop_index("ix_health_observations_person_id", table_name="health_observations")
    op.drop_index("ix_health_observations_observed_at", table_name="health_observations")
    op.drop_table("health_observations")
    op.drop_table("import_batches")
    op.drop_table("person_device_assignments")
    op.drop_table("devices")
    op.drop_table("household_memberships")
    op.drop_table("access_grants")
    op.drop_table("observation_types")
    op.drop_table("source_systems")
    op.drop_table("households")
    op.drop_table("user_accounts")
    op.drop_table("persons")
