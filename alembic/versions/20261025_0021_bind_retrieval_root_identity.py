"""bind retrieval authorization to the opened directory identity

Revision ID: 20261025_0021
Revises: 20261023_0020
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261025_0021"
down_revision: str | None = "20261023_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable so databases upgrade safely. Legacy roots have no trustworthy
    # approval-time identity and retrieval intentionally fails closed for them.
    op.add_column(
        "assistant_retrieval_roots",
        sa.Column("root_identity", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("assistant_retrieval_roots", "root_identity")
