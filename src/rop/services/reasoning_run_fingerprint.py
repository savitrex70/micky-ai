"""Task 125: deterministic reasoning-run input fingerprint binding.

One canonical SHA-256 fingerprint over the normalized Task 124 input
snapshot. Deterministic serialization with sorted mapping keys;
ordered collections keep their canonical order (reordering candidates
or evidence is a material input change). The fingerprint is
reproducible for identical logical input and differs for semantically
different input. Verification only compares -- a mismatch is reported,
never silently replaced or recomputed from untrusted output.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

__all__ = [
    "compute_snapshot_fingerprint",
    "verify_snapshot_fingerprint",
]

_FINGERPRINT_PATTERN_LENGTH = 64


def compute_snapshot_fingerprint(snapshot: Mapping[str, Any]) -> str:
    """Compute the canonical fingerprint of an input snapshot."""
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_snapshot_fingerprint(
    snapshot: Mapping[str, Any], expected_fingerprint: str
) -> list[str]:
    """Compare a snapshot against a claimed fingerprint.

    Returns issue strings (empty when bound). Never raises on hostile
    input shapes: an unmeasurable snapshot reports instead of escaping.
    """
    if not isinstance(expected_fingerprint, str) or (
        len(expected_fingerprint) != _FINGERPRINT_PATTERN_LENGTH
    ):
        return ["claimed input fingerprint is malformed"]
    try:
        actual = compute_snapshot_fingerprint(snapshot)
    except Exception as exc:
        return ["input fingerprint could not be recomputed: " + type(exc).__name__]
    if actual != expected_fingerprint:
        return ["input fingerprint mismatch: snapshot does not match run"]
    return []
