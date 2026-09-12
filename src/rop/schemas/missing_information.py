from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MissingInformationRead(BaseModel):
    """Serialized missing-information item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    template: str
    item: str
    created_at: datetime
