from pydantic import BaseModel, Field

from rop.schemas.observation import ObservationRead


class ObservationExtractionRequest(BaseModel):
    """Free-text input for rule-based observation extraction."""

    text: str = Field(min_length=1)


class ObservationExtractionResponse(BaseModel):
    """Structured observations created from one extraction request."""

    observations: list[ObservationRead]
