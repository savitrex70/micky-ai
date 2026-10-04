from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from rop.database import Base

if TYPE_CHECKING:
    from rop.models.candidate_hypothesis import CandidateHypothesis
    from rop.models.entity import Entity
    from rop.models.evaluated_evidence import EvaluatedEvidence
    from rop.models.hypothesis import Hypothesis
    from rop.models.missing_information import MissingInformation
    from rop.models.observation import Observation
    from rop.models.reasoning_step import ReasoningStep
    from rop.models.template_match import TemplateMatch


class ReasoningSession(Base):
    """Persisted state for one reasoning session."""

    __tablename__ = "reasoning_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    current_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    entities: Mapped[list["Entity"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    hypotheses: Mapped[list["Hypothesis"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    missing_information: Mapped[list["MissingInformation"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    template_matches: Mapped[list["TemplateMatch"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reasoning_steps: Mapped[list["ReasoningStep"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    candidate_hypotheses: Mapped[list["CandidateHypothesis"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    evaluated_evidence: Mapped[list["EvaluatedEvidence"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
