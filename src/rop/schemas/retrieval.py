"""Schema contracts for deterministic, offline local-file retrieval."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Maximum number of authorized roots one search request may load and process.
#
# Each root costs real filesystem work (path validation, a component-by-component
# no-follow open, mount-table refreshes, and at least one directory scan) even
# when it is empty, so empty or low-entry roots are not bounded by the global
# entry counter. 25 keeps the worst case (25 roots x 250 directories per root)
# in the same order as the existing per-request ceilings (10,000 entries,
# 1,000 files) and is far above the handful of folders a person authorizes.
# The database query and the processing loop both enforce this value; roots
# beyond it are reported as skipped, never silently implied to be searched.
MAX_RETRIEVAL_ROOTS_PER_REQUEST = 25


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
    # Root accounting is reported separately from file accounting so a skipped
    # root is never disguised as a skipped file. ``roots_examined`` counts roots
    # whose processing began; ``roots_skipped`` counts authorized roots that were
    # not searched in this request because the per-request root limit or another
    # global work limit stopped the search. Both default to 0 for older callers.
    # ``roots_rejected`` is the subset of examined roots refused by validation
    # (identity, path/network policy, failed secure open); they were not searched
    # and are never counted in ``skipped_files``. Unsearched roots in total are
    # ``roots_rejected + roots_skipped``.
    roots_examined: int = 0
    roots_skipped: int = 0
    roots_rejected: int = 0
    roots_limit: int = MAX_RETRIEVAL_ROOTS_PER_REQUEST
    # Non-file/unclassified entries refused by traversal; never a file count.
    skipped_entries: int = 0
