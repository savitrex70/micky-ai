"""Task 107: Minimal schema for provider isolation.

Only the structural-contract source constant is exposed here.
All boundary logic lives in the service layer.
"""

from __future__ import annotations

from rop.services.llm_provider_isolation import (
    LLM_PROVIDER_ISOLATION_SOURCE_TASK_107,
)

__all__ = ["LLM_PROVIDER_ISOLATION_SOURCE_TASK_107"]
