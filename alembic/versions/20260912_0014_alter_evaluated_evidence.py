"""alter evaluated evidence: separate rule weight from match contribution

Revision ID: 20260912_0014
Revises: 20260911_0013
Create Date: 2026-09-12

Adds the columns needed to distinguish a rule's static ``weight`` from how
much of that rule's findings were actually matched in a given session
(``matched_finding_count`` / ``total_finding_count`` / ``match_strength``),
plus a computed ``contribution`` (weight * match_strength) that a future
scoring engine should use instead of the raw rule weight. Also adds
``contributing_observation_ids`` / ``contributing_entity_ids`` so evidence
that was matched across multiple observations or entities (session-wide
evaluation, not one observation at a time) keeps full traceability instead
of pointing at a single arbitrary source.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0014"
down_revision: str | None = "20260911_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evaluated_evidence",
        sa.Column(
            "matched_finding_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "evaluated_evidence",
        sa.Column(
            "total_finding_count", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "evaluated_evidence",
        sa.Column("match_strength", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "evaluated_evidence",
        sa.Column("contribution", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "evaluated_evidence",
        sa.Column(
            "contributing_observation_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "evaluated_evidence",
        sa.Column(
            "contributing_entity_ids", sa.JSON(), nullable=False, server_default="[]"
        ),
    )


def downgrade() -> None:
    op.drop_column("evaluated_evidence", "contributing_entity_ids")
    op.drop_column("evaluated_evidence", "contributing_observation_ids")
    op.drop_column("evaluated_evidence", "contribution")
    op.drop_column("evaluated_evidence", "match_strength")
    op.drop_column("evaluated_evidence", "total_finding_count")
    op.drop_column("evaluated_evidence", "matched_finding_count")
