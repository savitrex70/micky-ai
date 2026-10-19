"""create assistant conversations and messages tables

Revision ID: 20261019_0018
Revises: 20261017_0017
Create Date: 2026-10-19

Durable storage for user-visible assistant conversations (Task 228). Two
tables are created: ``assistant_conversations`` and ``assistant_messages``.

Neither table has a foreign key to any clinical table, and no clinical
table is altered. The messages table is owned by the conversations table
through ``ON DELETE CASCADE`` so that deleting one conversation removes
only its own messages and never another conversation's, and never any
clinical reasoning data.

``role`` is constrained to ``user`` or ``assistant``. There is no role
for hidden internal instructions; a value such as ``system`` is rejected
by the check constraint. ``sequence`` is non-negative and unique per
conversation, so a conversation cannot contain two messages at the same
position.

Only these new tables, their constraints, and their indexes are created.
No existing table is altered or backfilled, and nothing is created at
runtime: the schema exists only through this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_0018"
down_revision: str | None = "20261017_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_VALUES = "'user', 'assistant'"


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_conversations_created_at",
        "assistant_conversations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_conversations_updated_at",
        "assistant_conversations",
        ["updated_at"],
        unique=False,
    )

    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"role IN ({_ROLE_VALUES})",
            name="ck_assistant_messages_role",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_assistant_messages_sequence"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["assistant_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_assistant_messages_conversation_sequence",
        ),
    )
    op.create_index(
        "ix_assistant_messages_conversation_id",
        "assistant_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_assistant_messages_conversation_sequence",
        "assistant_messages",
        ["conversation_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assistant_messages_conversation_sequence",
        table_name="assistant_messages",
    )
    op.drop_index(
        "ix_assistant_messages_conversation_id",
        table_name="assistant_messages",
    )
    op.drop_table("assistant_messages")
    op.drop_index(
        "ix_assistant_conversations_updated_at",
        table_name="assistant_conversations",
    )
    op.drop_index(
        "ix_assistant_conversations_created_at",
        table_name="assistant_conversations",
    )
    op.drop_table("assistant_conversations")
