"""Server-side executor contract and registry for confirmed operations.

An executor is the only code permitted to perform a state-changing
operation, and it is reachable only from the trusted dispatch boundary,
after a confirmation has been verified and consumed. Nothing here is a
public endpoint, a capability, or a request field: a client cannot name,
select, supply, or replace an executor, and no request field is ever read
to choose one.

The default registry is deliberately **empty**. This build registers no
production state-changing capability and no production executor, so a
consequential operation cannot run outside a test. An empty registry is
not permission: whenever no executor is registered for an operation, the
operation is not executed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum

from rop.schemas.authorization import AuthorizedScope, ProposedOperation

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class ExecutorResult(StrEnum):
    """What an executor established about the operation it ran."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ExecutorError(RuntimeError):
    """Raised when an executor ran and established that the operation failed."""


class ExecutorInterrupted(RuntimeError):
    """Raised when an executor was interrupted and the outcome is unknown."""


Executor = Callable[[ProposedOperation, AuthorizedScope], ExecutorResult]
"""The internal executor contract.

An executor receives the canonical stored operation and the verified
authorization that covers exactly it, and returns an ``ExecutorResult``.
Raising ``ExecutorError`` is an established failure; raising
``ExecutorInterrupted`` leaves the outcome unestablished. The caller must
never report success for an unestablished or failed outcome.
"""


class ExecutorRegistry:
    """A server-side-only map from operation identifier to executor."""

    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}

    def register(self, operation_id: str, executor: Executor) -> None:
        if not isinstance(operation_id, str) or not _IDENTIFIER_PATTERN.fullmatch(
            operation_id
        ):
            raise ValueError("invalid executor operation identifier")
        if operation_id in self._executors:
            raise ValueError("duplicate executor operation identifier")
        if not callable(executor):
            raise ValueError("executor must be callable")
        self._executors[operation_id] = executor

    def get(self, operation_id: str) -> Executor | None:
        """Return the executor for ``operation_id``, or ``None``."""
        return self._executors.get(operation_id)

    def __contains__(self, operation_id: object) -> bool:
        return operation_id in self._executors

    def __len__(self) -> int:
        return len(self._executors)


def build_default_executor_registry() -> ExecutorRegistry:
    """Return the production registry, which is empty on purpose.

    No reviewed, explicitly approved production executor exists in this
    build, so a consequential operation remains non-executable outside
    tests. Registering a capability does not register an executor.
    """
    return ExecutorRegistry()


__all__ = [
    "Executor",
    "ExecutorError",
    "ExecutorInterrupted",
    "ExecutorRegistry",
    "ExecutorResult",
    "build_default_executor_registry",
]
