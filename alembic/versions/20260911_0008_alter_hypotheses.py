"""alter hypotheses table for updated framework

Revision ID: 20260911_0008
Revises: 20260911_0007
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0008"
down_revision: str | None = "20260911_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.add_column(
            sa.Column("category", sa.String(length=100), nullable=False)
        )
        batch_op.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "likelihood_score", sa.Float(), nullable=False, server_default="0.0"
            )
        )
        batch_op.add_column(
            sa.Column("rank", sa.Integer(), nullable=False, server_default="0")
        )

    op.execute(
        "UPDATE hypotheses SET likelihood_score = likelihood, rank = ranking"
    )

    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.alter_column("likelihood_score", server_default=None)
        batch_op.alter_column("rank", server_default=None)
        batch_op.drop_column("likelihood")
        batch_op.drop_column("ranking")


def downgrade() -> None:
    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.add_column(
            sa.Column("likelihood", sa.Float(), nullable=False, server_default="0.0")
        )
        batch_op.add_column(
            sa.Column("ranking", sa.Integer(), nullable=False, server_default="0")
        )

    op.execute("UPDATE hypotheses SET likelihood = likelihood_score, ranking = rank")

    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.alter_column("likelihood", server_default=None)
        batch_op.alter_column("ranking", server_default=None)
        batch_op.drop_column("likelihood_score")
        batch_op.drop_column("rank")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("reason")
        batch_op.drop_column("category")
