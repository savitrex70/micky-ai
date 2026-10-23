"""create local assistant workspace tables

Revision ID: 20261023_0019
Revises: 20261019_0018
Create Date: 2026-10-23

Notes, tasks, reminders, explicitly authorized retrieval roots, and minimal
idempotency receipts are separate from clinical reasoning data.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0019"
down_revision: str | None = "20261019_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=128), nullable=True),
        sa.Column(
            "completed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('note', 'task', 'reminder')",
            name="ck_assistant_items_kind",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assistant_items_title",
        ),
        sa.CheckConstraint(
            "(kind = 'reminder' AND due_at IS NOT NULL AND timezone IS NOT NULL) "
            "OR (kind <> 'reminder' AND due_at IS NULL AND timezone IS NULL)",
            name="ck_assistant_items_reminder_time",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_items_kind_updated_at",
        "assistant_items",
        ["kind", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_items_reminder_due",
        "assistant_items",
        ["kind", "completed", "due_at"],
        unique=False,
    )

    op.create_table(
        "assistant_retrieval_roots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "path", name="uq_assistant_retrieval_roots_path"
        ),
    )
    op.create_index(
        "ix_assistant_retrieval_roots_created_at",
        "assistant_retrieval_roots",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "assistant_operation_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("operation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_code", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED')",
            name="ck_assistant_operation_receipts_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_assistant_operation_receipts_key",
        ),
    )
    op.create_index(
        "ix_assistant_operation_receipts_created_at",
        "assistant_operation_receipts",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_operation_receipts_created_at",
        table_name="assistant_operation_receipts",
    )
    op.drop_table("assistant_operation_receipts")
    op.drop_index(
        "ix_assistant_retrieval_roots_created_at",
        table_name="assistant_retrieval_roots",
    )
    op.drop_table("assistant_retrieval_roots")
    op.drop_index(
        "ix_assistant_items_reminder_due",
        table_name="assistant_items",
    )
    op.drop_index(
        "ix_assistant_items_kind_updated_at",
        table_name="assistant_items",
    )
    op.drop_table("assistant_items")
