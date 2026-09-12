from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.reasoning_session import ReasoningSession

if TYPE_CHECKING:
    from rop.models.evaluated_evidence import EvaluatedEvidence


class Observation(Base):
    """Persisted observation belonging to one reasoning session."""

    __tablename__ = "observations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="observations")
    evaluated_evidence: Mapped[list["EvaluatedEvidence"]] = relationship(
        back_populates="observation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
