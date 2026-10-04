"""alter evidence table for updated framework

Revision ID: 20260911_0009
Revises: 20260911_0008
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0009"
down_revision: str | None = "20260911_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("strength", sa.String(length=50), nullable=True))
        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            )
        )

    op.execute("UPDATE evidence SET type = 'unknown', strength = 'moderate'")

    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column("session_id", nullable=False)
        batch_op.alter_column("type", nullable=False)
        batch_op.alter_column("strength", nullable=False)
        batch_op.alter_column("created_at", nullable=False)
        batch_op.drop_column("stance")
        batch_op.drop_column("timestamp")

    op.create_index("ix_evidence_session_id", "evidence", ["session_id"], unique=False)
    op.create_foreign_key(
        "fk_evidence_session_id",
        "evidence",
        "reasoning_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch_op:
        batch_op.add_column(
            sa.Column(
                "stance",
                sa.String(length=20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )

    op.execute("UPDATE evidence SET stance = type")

    with op.batch_alter_table("evidence") as batch_op:
        batch_op.alter_column("stance", server_default=None)
        batch_op.alter_column("timestamp", server_default=None)
        batch_op.drop_column("type")
        batch_op.drop_column("strength")
        batch_op.drop_column("created_at")
        batch_op.drop_column("session_id")

    op.drop_constraint("fk_evidence_session_id", "evidence", type_="foreignkey")
    op.drop_index("ix_evidence_session_id", table_name="evidence")
