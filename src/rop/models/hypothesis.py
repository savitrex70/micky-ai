from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.reasoning_session import ReasoningSession

if TYPE_CHECKING:
    from rop.models.evidence import Evidence


class HypothesisStatus(StrEnum):
    """Allowed status values for a clinical hypothesis."""

    PENDING = "pending"
    ACTIVE = "active"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"


class Hypothesis(Base):
    """Persisted hypothesis belonging to one reasoning session."""

    __tablename__ = "hypotheses"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[HypothesisStatus] = mapped_column(
        String(50), nullable=False, default=HypothesisStatus.PENDING
    )
    likelihood_score: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="hypotheses")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="hypothesis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
