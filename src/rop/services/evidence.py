from uuid import UUID

from sqlalchemy.orm import Session

from rop.models import Evidence
from rop.repositories import EvidenceRepository
from rop.schemas import EvidenceCreate, EvidenceUpdate


class EvidenceService:
    """CRUD service for evidence records."""

    def __init__(self, repository: EvidenceRepository | None = None) -> None:
        self.repository = repository or EvidenceRepository()

    def create(self, db: Session, data: EvidenceCreate) -> Evidence:
        return self.repository.create(db, data)

    def get(self, db: Session, evidence_id: UUID) -> Evidence | None:
        return self.repository.get(db, evidence_id)

    def list_by_hypothesis(
        self,
        db: Session,
        hypothesis_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Evidence]:
        return self.repository.list_by_hypothesis(
            db, hypothesis_id, offset=offset, limit=limit
        )

    def list_by_session(
        self,
        db: Session,
        session_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Evidence]:
        return self.repository.list_by_session(
            db, session_id, offset=offset, limit=limit
        )

    def update(
        self,
        db: Session,
        evidence_id: UUID,
        data: EvidenceUpdate,
    ) -> Evidence | None:
        evidence = self.repository.get(db, evidence_id)
        if evidence is None:
            return None
        return self.repository.update(db, evidence, data)

    def delete(self, db: Session, evidence_id: UUID) -> bool:
        evidence = self.repository.get(db, evidence_id)
        if evidence is None:
            return False
        self.repository.delete(db, evidence)
        return True
