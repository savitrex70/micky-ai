from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rop.missing_information import MissingInformationItem
from rop.models import MissingInformation


class MissingInformationRepository:
    """Database operations for missing-information records."""

    def replace_for_session(
        self,
        db: Session,
        session_id: UUID,
        items: list[MissingInformationItem],
        template_name: str | None = None,
    ) -> list[MissingInformation]:
        template_names = {item.template for item in items}
        if template_name is not None:
            template_names.add(template_name)
        if template_names:
            db.execute(
                delete(MissingInformation).where(
                    MissingInformation.session_id == session_id,
                    MissingInformation.template.in_(template_names),
                )
            )
        records = [
            MissingInformation(
                session_id=session_id,
                template=item.template,
                item=item.label,
            )
            for item in items
        ]
        db.add_all(records)
        db.commit()
        for record in records:
            db.refresh(record)
        return records

    def list_by_session(
        self, db: Session, session_id: UUID
    ) -> list[MissingInformation]:
        statement = (
            select(MissingInformation)
            .where(MissingInformation.session_id == session_id)
            .order_by(MissingInformation.created_at.asc())
        )
        return list(db.scalars(statement).all())
