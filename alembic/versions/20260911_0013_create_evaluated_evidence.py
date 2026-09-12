"""create evaluated evidence table

Revision ID: 20260911_0013
Revises: 20260911_0012
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0013"
down_revision: str | None = "20260911_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluated_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("rule_id", sa.String(length=255), nullable=False),
        sa.Column("relationship", sa.String(length=50), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["reasoning_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["candidate_hypotheses.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["observations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluated_evidence_session_id",
        "evaluated_evidence",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_evaluated_evidence_hypothesis_id",
        "evaluated_evidence",
        ["hypothesis_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evaluated_evidence_hypothesis_id", table_name="evaluated_evidence"
    )
    op.drop_index(
        "ix_evaluated_evidence_session_id", table_name="evaluated_evidence"
    )
    op.drop_table("evaluated_evidence")
