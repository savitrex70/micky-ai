"""create reasoning run receipts table

Revision ID: 20260930_0015
Revises: 20260912_0014
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0015"
down_revision: str | None = "20260912_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reasoning_run_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("exogenous_snapshot", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["reasoning_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reasoning_run_receipts_session_id",
        "reasoning_run_receipts",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_reasoning_run_receipts_session_fingerprint",
        "reasoning_run_receipts",
        ["session_id", "input_fingerprint"],
        # Canonical identities are unique: concurrent identical
        # successful executions cannot duplicate them. History across
        # distinct fingerprints is preserved (no two runs share inputs).
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reasoning_run_receipts_session_fingerprint",
        table_name="reasoning_run_receipts",
    )
    op.drop_index(
        "ix_reasoning_run_receipts_session_id",
        table_name="reasoning_run_receipts",
    )
    op.drop_table("reasoning_run_receipts")
