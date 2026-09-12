from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.reasoning_session import ReasoningSession


class TemplateMatch(Base):
    """Persisted template match result for one reasoning session."""

    __tablename__ = "template_matches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_observations: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    matched_entities: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    candidates: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="template_matches")
