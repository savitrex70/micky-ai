"""Versioned response contracts for personal-data export."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PersonalDataExportCounts(BaseModel):
    """Counts for the exported domains; excludes clinical and confirmation data."""

    model_config = ConfigDict(extra="forbid")

    conversations: int
    messages: int
    workspace_items: int


class PersonalDataExportPage(BaseModel):
    """One bounded page in the v1 personal-data export stream."""

    model_config = ConfigDict(extra="forbid")

    export_format: Literal["micky-ai-personal-data"] = "micky-ai-personal-data"
    schema_version: Literal[1] = 1
    generated_at: datetime
    offset: int
    limit: int
    total_records: int
    counts: PersonalDataExportCounts
    next_offset: int | None
    complete: bool
    records: list[dict[str, object]]
