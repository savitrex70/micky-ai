"""create short-lived assistant clarification state

Revision ID: 20261023_0020
Revises: 20261023_0019
Create Date: 2026-10-23

Pending clarification state belongs only to saved assistant conversations.
Temporary message and partial-operation values are cleared on consumption.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0020"
down_revision: str | None = "20261023_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_pending_clarifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("clarification_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("capability_identifier", sa.String(length=64), nullable=False),
        sa.Column("original_message", sa.Text(), nullable=False),
        sa.Column("partial_operation", sa.JSON(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column("question", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONSUMED')",
            name="ck_assistant_pending_clarifications_status",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING') = (consumed_at IS NULL)",
            name="ck_assistant_pending_clarifications_consumed_at",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "clarification_id",
            name="uq_assistant_pending_clarifications_public_id",
        ),
    )
    op.create_index(
        "ix_assistant_pending_clarifications_conversation_status",
        "assistant_pending_clarifications",
        ["conversation_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_pending_clarifications_status_expires_at",
        "assistant_pending_clarifications",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_pending_clarifications_status_expires_at",
        table_name="assistant_pending_clarifications",
    )
    op.drop_index(
        "ix_assistant_pending_clarifications_conversation_status",
        table_name="assistant_pending_clarifications",
    )
    op.drop_table("assistant_pending_clarifications")
