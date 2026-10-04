from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base
from rop.models.reasoning_session import ReasoningSession


class StepType(StrEnum):
    """Allowed step types for a reasoning step."""

    INPUT = "input"
    OBSERVATION_EXTRACTION = "observation_extraction"
    ENTITY_RECOGNITION = "entity_recognition"
    TEMPLATE_MATCH = "template_match"
    MISSING_INFORMATION = "missing_information"
    HYPOTHESIS = "hypothesis"
    EVIDENCE = "evidence"
    DECISION = "decision"
    EXPLANATION = "explanation"


class ReasoningStep(Base):
    """Immutable audit trail record for a reasoning action."""

    __tablename__ = "reasoning_steps"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[StepType] = mapped_column(String(50), nullable=False)
    input_data: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    output_data: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ReasoningSession] = relationship(back_populates="reasoning_steps")
