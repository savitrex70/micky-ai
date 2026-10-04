"""Task 107: Minimal schema for provider isolation.

Defines the structural-contract source constant at the schema layer so
the service implementation depends toward schemas (never the reverse).
All boundary logic lives in the service layer.
"""

from __future__ import annotations

LLM_PROVIDER_ISOLATION_SOURCE_TASK_107 = "LLM_PROVIDER_ISOLATION_TASK_107"
"""Fixed structural-contract identifier for Task 107 results."""

__all__ = ["LLM_PROVIDER_ISOLATION_SOURCE_TASK_107"]
