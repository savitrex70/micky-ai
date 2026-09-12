from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.hypothesis import Hypothesis


class EvidenceType(StrEnum):
    """Allowed type values for evidence."""

    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class EvidenceStrength(StrEnum):
    """Allowed strength values for evidence."""

    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    VERY_WEAK = "very_weak"


class Evidence(Base):
    """Persisted evidence belonging to one hypothesis."""

    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    hypothesis_id: Mapped[UUID] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[EvidenceType] = mapped_column(
        String(50), nullable=False, default=EvidenceType.UNKNOWN
    )
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    strength: Mapped[EvidenceStrength] = mapped_column(
        String(50), nullable=False, default=EvidenceStrength.MODERATE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    hypothesis: Mapped[Hypothesis] = relationship(back_populates="evidence")
