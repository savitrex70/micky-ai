"""Schema contracts for deterministic, offline local-file retrieval."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RetrievalSearchRequest(BaseModel):
    """Search only explicitly authorized local roots."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=15, ge=1, le=30)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value or not value.isprintable():
            raise ValueError("query must be printable, non-blank text")
        return value


class RetrievalMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    snippet: str


class RetrievalSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    matches: list[RetrievalMatch]
    files_examined: int
    skipped_files: int
