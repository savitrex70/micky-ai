"""create user-controlled personal memory entries

Revision ID: 20261028_0022
Revises: 20261025_0021
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0022"
down_revision: str | None = "20261025_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_memory_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "entry_type",
            sa.String(length=16),
            server_default="memory",
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
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
            "entry_type IN ('memory', 'preference')",
            name="ck_assistant_memory_entries_type",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_assistant_memory_entries_title",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_assistant_memory_entries_content",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_memory_entries_updated_at",
        "assistant_memory_entries",
        ["updated_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_memory_entries_updated_at",
        table_name="assistant_memory_entries",
    )
    op.drop_table("assistant_memory_entries")
