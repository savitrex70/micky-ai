"""create assistant confirmations table

Revision ID: 20261017_0017
Revises: 20261002_0016
Create Date: 2026-10-17

Durable storage for the approved per-operation confirmation design
(Task 222, Task 223). The table is intentionally independent of every
clinical table: it has no foreign keys, so no reasoning session,
hypothesis, evidence, provenance, certification, or audit record can be
created, modified, or joined as a side effect of storing a confirmation.

Only this new table, its constraints, and its indexes are created. No
existing table is altered or backfilled, and nothing is created at
runtime: the schema exists only through this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261017_0017"
down_revision: str | None = "20261002_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_VALUES = (
    "'PENDING', 'CONSUMED', 'REJECTED', 'CANCELLED', "
    "'EXPIRED', 'INVALIDATED', 'LOCKED'"
)
_OUTCOME_VALUES = "'NOT_RUN', 'FAILED', 'SUCCEEDED', 'UNKNOWN_AFTER_CONSUME'"


def upgrade() -> None:
    op.create_table(
        "assistant_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.String(length=128), nullable=False),
        sa.Column("display_code_hash", sa.String(length=64), nullable=True),
        sa.Column("display_code_salt", sa.String(length=64), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=512), nullable=True),
        sa.Column("scope", sa.String(length=512), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("policy_identity", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("required_risk", sa.String(length=20), nullable=False),
        sa.Column("required_reason", sa.String(length=64), nullable=False),
        sa.Column(
            "failed_code_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=True),
        sa.Column(
            "material_redacted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("material_digest", sa.String(length=64), nullable=True),
        sa.Column("material_digest_salt", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"status IN ({_STATUS_VALUES})",
            name="ck_assistant_confirmations_status",
        ),
        sa.CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_OUTCOME_VALUES})",
            name="ck_assistant_confirmations_outcome",
        ),
        sa.CheckConstraint(
            "failed_code_attempts >= 0 AND failed_code_attempts <= 5",
            name="ck_assistant_confirmations_failed_code_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING') = (terminal_at IS NULL)",
            name="ck_assistant_confirmations_terminal_timestamp",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING') = (display_code_hash IS NOT NULL)",
            name="ck_assistant_confirmations_verifier_presence",
        ),
        sa.CheckConstraint(
            "(display_code_hash IS NULL) = (display_code_salt IS NULL)",
            name="ck_assistant_confirmations_verifier_pair",
        ),
        sa.CheckConstraint(
            "(material_digest IS NULL) = (material_digest_salt IS NULL)",
            name="ck_assistant_confirmations_material_digest_pair",
        ),
        sa.CheckConstraint(
            "material_redacted = (material_digest IS NOT NULL)",
            name="ck_assistant_confirmations_redaction_digest",
        ),
        sa.CheckConstraint(
            "NOT material_redacted OR redacted_at IS NOT NULL",
            name="ck_assistant_confirmations_redacted_at",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "challenge_id", name="uq_assistant_confirmations_challenge_id"
        ),
    )
    op.create_index(
        "ix_assistant_confirmations_status_terminal_at",
        "assistant_confirmations",
        ["status", "terminal_at"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_confirmations_expires_at",
        "assistant_confirmations",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_confirmations_expires_at",
        table_name="assistant_confirmations",
    )
    op.drop_index(
        "ix_assistant_confirmations_status_terminal_at",
        table_name="assistant_confirmations",
    )
    op.drop_table("assistant_confirmations")
