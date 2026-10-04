from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship as orm_relationship

from rop.database import Base

if TYPE_CHECKING:
    from rop.models.candidate_hypothesis import CandidateHypothesis
    from rop.models.entity import Entity
    from rop.models.observation import Observation
    from rop.models.reasoning_session import ReasoningSession


class EvaluatedEvidence(Base):
    """Persisted evidence item linking observations/entities to candidate hypotheses."""

    __tablename__ = "evaluated_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("reasoning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hypothesis_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL"),
        nullable=True,
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"),
        nullable=True,
    )
    rule_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship: Mapped[str] = mapped_column(String(50), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    matched_finding_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    total_finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    match_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    contribution: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    contributing_observation_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    contributing_entity_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["ReasoningSession"] = orm_relationship(
        back_populates="evaluated_evidence"
    )
    hypothesis: Mapped["CandidateHypothesis"] = orm_relationship(
        back_populates="evaluated_evidence"
    )
    observation: Mapped["Observation | None"] = orm_relationship(
        back_populates="evaluated_evidence"
    )
    entity: Mapped["Entity | None"] = orm_relationship(
        back_populates="evaluated_evidence"
    )
