"""create reasoning steps table

Revision ID: 20260911_0010
Revises: 20260911_0009
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0010"
down_revision: str | None = "20260911_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reasoning_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=50), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
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
        "ix_reasoning_steps_session_id",
        "reasoning_steps",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_reasoning_steps_step_number",
        "reasoning_steps",
        ["session_id", "step_number"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_reasoning_steps_step_number", table_name="reasoning_steps")
    op.drop_index("ix_reasoning_steps_session_id", table_name="reasoning_steps")
    op.drop_table("reasoning_steps")
