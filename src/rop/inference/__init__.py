"""Task 212: local CPU inference runtime package.

Explicitly invoked, in-process CPU execution of the Task 209 model
from a caller-selected Task 211 checkpoint. Importing this package
never loads weights and never runs inference.
"""

from rop.inference.runtime import (
    InferenceError,
    InferenceSession,
    load_inference_session,
    run_inference,
)

__all__ = [
    "InferenceError",
    "InferenceSession",
    "load_inference_session",
    "run_inference",
]
