from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from rop.models import Observation
from rop.schemas import ObservationCreate, ObservationUpdate


class ObservationRepository:
    """Database operations for observation records."""

    def create(self, db: Session, data: ObservationCreate) -> Observation:
        observation = Observation(
            session_id=data.session_id,
            text=data.text,
            type=data.type,
            confidence=data.confidence,
            source=data.source,
        )
        db.add(observation)
        db.commit()
        db.refresh(observation)
        return observation

    def create_many(
        self, db: Session, data: list[ObservationCreate]
    ) -> list[Observation]:
        observations = [
            Observation(
                session_id=item.session_id,
                text=item.text,
                type=item.type,
                confidence=item.confidence,
                source=item.source,
            )
            for item in data
        ]
        db.add_all(observations)
        db.commit()
        for observation in observations:
            db.refresh(observation)
        return observations

    def get(self, db: Session, observation_id: UUID) -> Observation | None:
        return db.get(Observation, observation_id)

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Observation]:
        statement = (
            select(Observation)
            .where(Observation.session_id == session_id)
            .order_by(Observation.timestamp.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(
        self,
        db: Session,
        observation: Observation,
        data: ObservationUpdate,
    ) -> Observation:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(observation, field, value)

        db.add(observation)
        db.commit()
        db.refresh(observation)
        return observation

    def delete(self, db: Session, observation: Observation) -> None:
        db.delete(observation)
        db.commit()
