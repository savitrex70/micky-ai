"""Task 108: Privacy and prompt-injection regression boundary.

Pure boundary-test helpers for validating LLM request payloads against
privacy leaks and adversarial prompt-injection patterns.

All functions are pure: no DB, no HTTP, no provider calls, no mutation,
deterministic. Used as a regression boundary in tests and optionally
in production guardrails.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from rop.schemas.llm_privacy_boundary import (
    LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108,
)

__all__ = [
    "LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108",
    "check_payload_privacy",
    "check_adversarial_text",
    "validate_llm_input_boundary",
]

# ---------------------------------------------------------------------------
# Forbidden payload patterns (privacy / secrets leakage)
# ---------------------------------------------------------------------------
# These patterns should NEVER appear in a serialized LLM payload.
# All patterns are case-insensitive where applicable.

# Credential / secret patterns. Values allow word chars plus the
# base64url/JWT punctuation (dots, slashes, +, =) so real leaked tokens
# match; the 16+ length floor keeps short placeholders mention-only.
_CRED_VALUE = r"[\w\-.+/=]{16,}"
_CREDENTIAL_PATTERNS = (
    r"api[_-]?key\s*[:=]\s*" + _CRED_VALUE,  # api_key: xxx / api-key=xxx
    r"api[_-]?secret\s*[:=]\s*" + _CRED_VALUE,  # api_secret: xxx
    r"access[_-]?token\s*[:=]\s*" + _CRED_VALUE,  # access_token: xxx
    r"bearer\s+" + _CRED_VALUE,  # Bearer xxx
    r"password\s*[:=]\s*\S+",  # password: xxx
    r"passwd\s*[:=]\s*\S+",  # passwd: xxx
    r"secret\s*[:=]\s*\S+",  # secret: xxx
    r"token\s*[:=]\s*" + _CRED_VALUE,  # token: xxx (long enough to be real)
    r"private[_-]?key\s*[:=]\s*\S+",  # private_key: xxx
    r"client[_-]?secret\s*[:=]\s*\S+",  # client_secret: xxx
    r"aws[_-]?access[_-]?key(?:[_-]?id)?\s*[:=]\s*\S+",  # aws_access_key[_id]: xxx
    r"aws[_-]?secret(?:[_-]?access)?[_-]?key\s*[:=]\s*\S+",  # aws_secret[_access]_key
)

# Environment variable references
_ENV_VAR_PATTERNS = (
    r"\$\{\w+\}",  # ${VAR}
    r"\$\w+",  # $VAR
    r"%\w+%",  # %VAR%
)

# Filesystem paths (absolute paths that could leak internal structure)
_FILESYSTEM_PATH_PATTERNS = (
    r"/etc/",  # Unix system config
    r"/var/",  # Unix variable data
    r"/root/",  # Unix root home
    r"/home/",  # Unix user homes
    r"/opt/",  # Unix optional software
    r"/usr/",  # Unix user programs
    r"C:\\",  # Windows drive root
    r"C:/",  # Windows drive root (forward slash)
    r"\\\\",  # UNC paths
    r"\.\./",  # Directory traversal
    r"\.\.\\",  # Directory traversal (Windows)
)

# Database connection strings
_DB_CONNECTION_PATTERNS = (
    r"postgresql://",  # PostgreSQL
    r"postgres://",  # PostgreSQL (short)
    r"mysql://",  # MySQL
    r"sqlite://",  # SQLite
    r"mongodb://",  # MongoDB
    r"redis://",  # Redis
    r"mssql://",  # SQL Server
    r"oracle://",  # Oracle
    r"jdbc:",  # JDBC
)

# ORM / internal class references (SQLAlchemy and similar)
_ORM_REFERENCE_PATTERNS = (
    r"\bSQLAlchemy\b",
    r"\bSession\b",
    r"\bEngine\b",
    r"\bConnection\b",
    r"\bMapper\b",
    r"\bTable\b",
    r"\bColumn\b",
    r"\bMetaData\b",
    r"\bDeclarativeBase\b",
    r"\bdeclarative_base\b",
    r"\bscoped_session\b",
    r"\bsessionmaker\b",
    r"\bQuery\b",
    r"\bselect\b.*\bfrom\b",  # SQL-like (loose, but catches obvious)
    r"\binsert\b.*\binto\b",
    r"\bupdate\b.*\bset\b",
    r"\bdelete\b.*\bfrom\b",
    r"\bdrop\b.*\btable\b",
)

# Private dunder attributes
_DUNDER_PATTERNS = (r"__\w+__",)  # Any __dunder__ attribute

# Python object representations (memory addresses and instance reprs that
# leak runtime internals; legitimate clinical text never contains these)
_PYTHON_REPR_PATTERNS = (
    r"<[\w.]+\s+object\s+at\s+0x[0-9a-fA-F]+>",  # <Foo object at 0x7f...>
    r"0x[0-9a-fA-F]{8,}",  # raw memory addresses
)

# Combine all forbidden patterns with descriptive labels
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    # (label, regex)
    *[
        (f"credential:{label}", pat)
        for label, pat in (
            ("api_key", _CREDENTIAL_PATTERNS[0]),
            ("api_secret", _CREDENTIAL_PATTERNS[1]),
            ("access_token", _CREDENTIAL_PATTERNS[2]),
            ("bearer_token", _CREDENTIAL_PATTERNS[3]),
            ("password", _CREDENTIAL_PATTERNS[4]),
            ("passwd", _CREDENTIAL_PATTERNS[5]),
            ("secret", _CREDENTIAL_PATTERNS[6]),
            ("token", _CREDENTIAL_PATTERNS[7]),
            ("private_key", _CREDENTIAL_PATTERNS[8]),
            ("client_secret", _CREDENTIAL_PATTERNS[9]),
            ("aws_access_key", _CREDENTIAL_PATTERNS[10]),
            ("aws_secret_key", _CREDENTIAL_PATTERNS[11]),
        )
    ],
    *[(f"env_var:{i}", pat) for i, pat in enumerate(_ENV_VAR_PATTERNS)],
    *[(f"filesystem_path:{i}", pat) for i, pat in enumerate(_FILESYSTEM_PATH_PATTERNS)],
    *[(f"db_connection:{i}", pat) for i, pat in enumerate(_DB_CONNECTION_PATTERNS)],
    *[(f"orm_reference:{i}", pat) for i, pat in enumerate(_ORM_REFERENCE_PATTERNS)],
    *[(f"dunder_attribute:{i}", pat) for i, pat in enumerate(_DUNDER_PATTERNS)],
    *[(f"python_object_repr:{i}", pat) for i, pat in enumerate(_PYTHON_REPR_PATTERNS)],
)

# Pre-compile all regexes for performance
_COMPILED_FORBIDDEN: tuple[tuple[str, re.Pattern], ...] = tuple(
    (label, re.compile(pat, re.IGNORECASE)) for label, pat in _FORBIDDEN_PATTERNS
)


# ---------------------------------------------------------------------------
# Adversarial prompt-injection patterns
# ---------------------------------------------------------------------------
# These patterns indicate potential prompt-injection attempts.
# All checks are case-insensitive.

_ADVERSARIAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ignore_previous_instructions", r"ignore\s+previous\s+instructions?"),
    ("call_this_tool", r"call\s+this\s+tool"),
    ("change_the_database", r"change\s+the\s+database"),
    ("select_this_candidate", r"select\s+this\s+candidate"),
    ("reveal_hidden_data", r"reveal\s+hidden\s+data"),
    ("ignore_all_rules", r"ignore\s+all\s+rules"),
    ("you_are_now", r"you\s+are\s+now"),
    ("system_prompt", r"system\s+prompt"),
    ("admin_mode", r"admin\s+mode"),
    ("developer_mode", r"developer\s+mode"),
    ("bypass", r"\bbypass\b"),
    ("override", r"\boverride\b"),
    ("execute_code", r"execute\s+code"),
    ("run_command", r"run\s+command"),
    ("delete", r"\bdelete\b"),
    ("drop_table", r"drop\s+table"),
    ("insert_into", r"insert\s+into"),
    ("update_set", r"update\s+set"),
)

_COMPILED_ADVERSARIAL: tuple[tuple[str, re.Pattern], ...] = tuple(
    (label, re.compile(pat, re.IGNORECASE)) for label, pat in _ADVERSARIAL_PATTERNS
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_payload_privacy(serialized: Mapping[str, Any]) -> list[str]:
    """Scan a serialized payload for forbidden privacy-leak patterns.

    Recursively traverses all string values in the payload (including
    nested dicts and lists) and checks each against the forbidden
    pattern set.

    Args:
        serialized: A JSON-serializable mapping (output of serialize_context
                    or similar).

    Returns:
        List of violation descriptions. Empty if clean.
        Each violation is formatted as "privacy:<label>:<matched_text[:50]>".
    """
    violations: list[str] = []
    _scan_for_patterns(serialized, _COMPILED_FORBIDDEN, violations, "privacy")
    return violations


def check_adversarial_text(text: str) -> list[str]:
    """Scan a single text string for adversarial prompt-injection patterns.

    Args:
        text: Any string to scan (e.g., observation text, entity name,
              user input, model output).

    Returns:
        List of detected adversarial pattern descriptions. Empty if clean.
        Each detection is formatted as "adversarial:<label>".
    """
    if not isinstance(text, str):
        return []
    violations: list[str] = []
    for label, pattern in _COMPILED_ADVERSARIAL:
        match = pattern.search(text)
        if match:
            violations.append(f"adversarial:{label}")
    return violations


def validate_llm_input_boundary(serialized: Mapping[str, Any]) -> list[str]:
    """Combined privacy + adversarial check for a full LLM input payload.

    Runs both check_payload_privacy (recursive scan of all string values)
    and check_adversarial_text on every string value in the payload.

    Args:
        serialized: A JSON-serializable mapping (LLM request payload).

    Returns:
        Combined list of all violations (privacy + adversarial).
        Empty if completely clean.
    """
    violations: list[str] = []
    violations.extend(check_payload_privacy(serialized))
    _scan_for_adversarial(serialized, violations)
    return violations


# ---------------------------------------------------------------------------
# Internal helpers (pure, deterministic)
# ---------------------------------------------------------------------------


def _scan_for_patterns(
    value: Any,
    compiled_patterns: tuple[tuple[str, re.Pattern], ...],
    violations: list[str],
    prefix: str,
) -> None:
    """Recursively scan all string values in a JSON-like structure."""
    if isinstance(value, str):
        for label, pattern in compiled_patterns:
            match = pattern.search(value)
            if match:
                matched = match.group(0)
                # Truncate long matches in violation description
                display = matched[:50] + ("..." if len(matched) > 50 else "")
                violations.append(f"{prefix}:{label}:{display}")
    elif isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(v, str) and isinstance(k, str):
                # Scan "key: value" jointly: a bare value can never match
                # less than it does here (it is a substring of the joint
                # string), while credential names living in KEYS (for
                # example {"aws_secret_access_key": "<secret>"}) only
                # become visible in the joined form.
                _scan_for_patterns(f"{k}: {v}", compiled_patterns, violations, prefix)
            else:
                _scan_for_patterns(v, compiled_patterns, violations, prefix)
    elif isinstance(value, list):
        for item in value:
            _scan_for_patterns(item, compiled_patterns, violations, prefix)
    # Other types (int, float, bool, None) are ignored


def _scan_for_adversarial(value: Any, violations: list[str]) -> None:
    """Recursively scan all string values for adversarial patterns."""
    if isinstance(value, str):
        adv = check_adversarial_text(value)
        violations.extend(adv)
    elif isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(v, str) and isinstance(k, str):
                _scan_for_adversarial(f"{k}: {v}", violations)
            else:
                _scan_for_adversarial(v, violations)
    elif isinstance(value, list):
        for item in value:
            _scan_for_adversarial(item, violations)
