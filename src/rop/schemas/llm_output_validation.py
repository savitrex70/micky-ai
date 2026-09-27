"""Task 105: Public exports for LLM output validation contracts.

This module re-exports the structural contract identifier so downstream
consumers can reference it without importing the service implementation.
"""

from rop.services.llm_output_validation import (
    LLM_OUTPUT_VALIDATION_SOURCE_TASK_105,
)

__all__ = ["LLM_OUTPUT_VALIDATION_SOURCE_TASK_105"]