"""add idempotency key to personal memory creation

Revision ID: 20261028_0023
Revises: 20261028_0022
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_0023"
down_revision: str | None = "20261028_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_memory_entries",
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "uq_assistant_memory_entries_idempotency_key",
        "assistant_memory_entries",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_assistant_memory_entries_idempotency_key",
        table_name="assistant_memory_entries",
    )
    op.drop_column("assistant_memory_entries", "idempotency_key")
