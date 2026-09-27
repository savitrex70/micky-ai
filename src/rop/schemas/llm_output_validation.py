"""Task 105: Public exports for LLM output validation contracts.

Defines the structural contract identifier at the schema layer so the
service implementation depends toward schemas (never the reverse).
"""

from __future__ import annotations

LLM_OUTPUT_VALIDATION_SOURCE_TASK_105 = "LLM_OUTPUT_VALIDATION_TASK_105"
"""Fixed structural-contract identifier for Task 105 validation results."""

__all__ = ["LLM_OUTPUT_VALIDATION_SOURCE_TASK_105"]
