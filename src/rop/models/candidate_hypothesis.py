from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.reasoning_session import ReasoningSession

if TYPE_CHECKING:
    from rop.models.evaluated_evidence import EvaluatedEvidence


class CandidateHypothesis(Base):
    """Persisted candidate hypothesis generated for a reasoning session."""

    __tablename__ = "candidate_hypotheses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False)
    initial_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    supporting_observations: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    contradicting_observations: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    missing_information: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ReasoningSession] = relationship(
        back_populates="candidate_hypotheses"
    )
    evaluated_evidence: Mapped[list["EvaluatedEvidence"]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
