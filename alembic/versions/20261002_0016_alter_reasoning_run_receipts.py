"""add input_snapshot to reasoning run receipts

Revision ID: 20261002_0016
Revises: 20260930_0015
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0016"
down_revision: str | None = "20260930_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: receipts written before this correction keep NULL and are
    # reported as explicitly not-persisted binding, never fabricated.
    op.add_column(
        "reasoning_run_receipts",
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reasoning_run_receipts", "input_snapshot")
