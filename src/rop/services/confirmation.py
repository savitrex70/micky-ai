"""Server-side confirmation workflow for one consequential operation.

This module owns the server side of the per-operation confirmation the
Task 222 design specifies and the Task 223 store prepared: it mints a
durable challenge for one sufficiently specified operation, verifies a
decision against the stored operation, the current authorization policy,
expiry, and the bounded attempt budget, and consumes the approval at most
once before an executor may run.

It deliberately does not define its own authorization rules or its own
store. It reuses Task 220's ``evaluate_authorization`` and
``AuthorizedScope``, Task 223's ``AssistantConfirmationRepository``, and
``authorization_policy_identity``, so there is no second policy table and
no parallel record table. This module is not an HTTP handler: the API
layer translates its results into sanitized response schemas.

No production state-changing capability or executor is defined here. The
workflow is exercised through test-only capabilities and test-only
executors; with the empty default executor registry, a consequential
operation cannot run.

Security-relevant behaviour:

* A challenge is minted only from a ``REQUIRE_CONFIRMATION`` decision,
  re-checked here, and only when an executor is registered for the exact
  operation. ``ALLOW``, ``CLARIFY``, ``DENY``, an unevaluable policy, and
  a missing executor never mint one.
* The challenge identifier is 128 bits from ``secrets`` and the display
  code is from an unambiguous alphabet; only a salted hash of the code is
  stored, and it is compared in constant time.
* Every value used after confirmation comes from the stored record, never
  from the confirming request.
* The stored effective policy identity is recomputed at confirmation and
  a mismatch invalidates the challenge instead of consuming it.
* Consumption is one atomic compare-and-set, committed *before* the
  executor runs, so a crash after the side effect cannot replay it.
* The display-code comparison and the failure counter share one row lock
  inside one transaction, so concurrent guesses cannot race past the
  budget and concurrent confirmations cannot both win.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from rop.authorization.executors import (
    Executor,
    ExecutorError,
    ExecutorInterrupted,
    ExecutorRegistry,
    ExecutorResult,
)
from rop.authorization.policy import (
    authorization_policy_identity,
    evaluate_authorization,
)
from rop.models.assistant_confirmation import AssistantConfirmation
from rop.repositories.assistant_confirmation import (
    AssistantConfirmationRepository,
    ConfirmationRecordError,
)
from rop.schemas.assistant_confirmation import (
    ConfirmationOutcome,
    PendingConfirmationDraft,
)
from rop.schemas.authorization import (
    REASON_OUTCOMES,
    AuthorizationOutcome,
    AuthorizationPolicy,
    AuthorizedScope,
    ProposedOperation,
    RiskLevel,
)
from rop.schemas.confirmation import ConfirmationDecision, ConfirmationDecisionStatus

CHALLENGE_LIFETIME = timedelta(minutes=5)
"""How long a challenge stays confirmable. Evaluated with the server clock."""

CHALLENGE_ID_BYTES = 16
"""128 bits of randomness for the opaque challenge identifier."""

DISPLAY_CODE_LENGTH = 6
"""Length of the human-checkable display code."""

DISPLAY_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
"""Unambiguous alphabet: no ``0``/``O`` and no ``1``/``I``/``L``."""

DISPLAY_CODE_SALT_BYTES = 16
"""Salt size for the stored display-code hash (32 hex characters)."""

DISPLAY_CODE_HASH_CONTEXT = b"rop.assistant-confirmation-display-code.v1"
"""Domain separator so a code digest cannot be confused with another hash."""

_WHITESPACE_RUN = re.compile(r"\s+")

_GENERIC_REFUSAL_MESSAGE = (
    "This confirmation could not be verified, so nothing was run and "
    "nothing was saved."
)
_CANCELLED_MESSAGE = "The confirmation was cancelled. The operation did not run."
_REJECTED_MESSAGE = "The confirmation was rejected. The operation did not run."
_UNAVAILABLE_MESSAGE = (
    "No executor is available for this operation in this build, so it was "
    "not run and cannot be completed here."
)
_EXECUTED_MESSAGE = "The operation was confirmed and ran successfully."
_FAILED_MESSAGE = (
    "The operation was confirmed and ran, but it failed. It will not be "
    "retried automatically."
)
_UNKNOWN_MESSAGE = (
    "The operation was confirmed, but its outcome could not be established. "
    "It will not be retried automatically."
)


class ChallengeIssueOutcome(StrEnum):
    """Why a challenge was or was not minted."""

    ISSUED = "ISSUED"
    NOT_REQUIRED = "NOT_REQUIRED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    DENIED = "DENIED"
    NO_EXECUTOR = "NO_EXECUTOR"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class IssuedChallenge:
    """The server-owned values a newly minted challenge exposes once."""

    challenge_id: str
    summary: str
    display_code: str
    expires_at: datetime


@dataclass(frozen=True)
class ChallengeIssueResult:
    """The outcome of asking the service to mint a challenge."""

    outcome: ChallengeIssueOutcome
    challenge: IssuedChallenge | None = None


@dataclass(frozen=True)
class DecisionResult:
    """The sanitized result of applying a decision to a challenge."""

    outcome: ConfirmationDecisionStatus
    message: str
    executed: bool


def _checked_now(now: datetime | None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("a timezone-aware timestamp is required")
    return current.astimezone(UTC)


def normalize_display_code(value: str) -> str:
    """Normalize an entered code for comparison.

    The contract is case-insensitive, and users may separate the groups of
    a code with whitespace, so surrounding and embedded whitespace is
    removed and the result is upper-cased. The alphabet contains no
    characters that case-folding could confuse.
    """
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RUN.sub("", value).upper()


def is_well_formed_display_code(value: str) -> bool:
    """Return True only for an exactly shaped code over the alphabet."""
    return len(value) == DISPLAY_CODE_LENGTH and all(
        character in DISPLAY_CODE_ALPHABET for character in value
    )


def derive_display_code_hash(code: str, salt_hex: str) -> str:
    """Return SHA-256 over the domain-separated, salted display code."""
    return hashlib.sha256(
        DISPLAY_CODE_HASH_CONTEXT
        + b"\x00"
        + bytes.fromhex(salt_hex)
        + b"\x00"
        + code.encode("utf-8")
    ).hexdigest()


def verify_display_code(
    record: AssistantConfirmation, display_code: str | None
) -> bool:
    """Compare a submitted code against a stored hash in constant time.

    A missing verifier (an already terminal record), a missing or
    malformed submission, and a wrong code all return ``False`` without
    distinguishing among them.
    """
    if display_code is None:
        return False
    stored_hash = record.display_code_hash
    stored_salt = record.display_code_salt
    if not stored_hash or not stored_salt:
        return False
    normalized = normalize_display_code(display_code)
    if not is_well_formed_display_code(normalized):
        return False
    candidate = derive_display_code_hash(normalized, stored_salt)
    return hmac.compare_digest(candidate, stored_hash)


def generate_challenge_id() -> str:
    """Return a fresh, opaque, URL-safe 128-bit challenge identifier."""
    return secrets.token_urlsafe(CHALLENGE_ID_BYTES)


def generate_display_code() -> str:
    """Return a fresh display code from the unambiguous alphabet."""
    return "".join(
        secrets.choice(DISPLAY_CODE_ALPHABET) for _ in range(DISPLAY_CODE_LENGTH)
    )


def build_operation_summary(
    operation: ProposedOperation,
    *,
    description: str,
    risk: RiskLevel,
) -> str:
    """Describe the exact stored operation without echoing user text.

    Everything here comes from server-side data: the policy rule's
    description and the canonical operation the challenge is bound to.
    The user's raw message is never part of the summary.
    """
    parts = [f"Operation: {operation.operation_id}."]
    if description:
        parts.append(f"What it would do: {description}")
    if operation.target is not None:
        parts.append(f"Target: {operation.target}.")
    if operation.scope is not None:
        parts.append(f"Scope: {operation.scope}.")
    if operation.parameters:
        rendered = ", ".join(
            f"{name}={value}" for name, value in sorted(operation.parameters.items())
        )
        parts.append(f"Parameters: {rendered}.")
    parts.append(f"Risk: {risk.value}.")
    return " ".join(parts)


def issue_challenge(
    db: Session,
    operation: ProposedOperation,
    *,
    policy: AuthorizationPolicy,
    executors: ExecutorRegistry,
    repository: AssistantConfirmationRepository | None = None,
    now: datetime | None = None,
) -> ChallengeIssueResult:
    """Mint a durable challenge for one operation, or explain why not.

    The policy is re-evaluated here, so a challenge exists only when the
    decision is still ``REQUIRE_CONFIRMATION`` and an executor is
    registered for the exact operation. The caller owns the transaction;
    this function stages one row and never commits.
    """
    repository = repository or AssistantConfirmationRepository()
    try:
        decision = evaluate_authorization(operation, policy=policy)
    except Exception:
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)

    if decision.outcome is AuthorizationOutcome.ALLOW:
        return ChallengeIssueResult(ChallengeIssueOutcome.NOT_REQUIRED)
    if decision.outcome is AuthorizationOutcome.CLARIFY:
        return ChallengeIssueResult(ChallengeIssueOutcome.CLARIFICATION_REQUIRED)
    if decision.outcome is AuthorizationOutcome.DENY:
        return ChallengeIssueResult(ChallengeIssueOutcome.DENIED)
    if decision.outcome is not AuthorizationOutcome.REQUIRE_CONFIRMATION:
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)
    if (
        REASON_OUTCOMES[decision.reason]
        is not AuthorizationOutcome.REQUIRE_CONFIRMATION
    ):
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)

    if executors.get(operation.operation_id) is None:
        return ChallengeIssueResult(ChallengeIssueOutcome.NO_EXECUTOR)

    try:
        identity = authorization_policy_identity(policy)
        rule = policy.rule(operation.operation_id)
        checked_operation = ProposedOperation.model_validate(operation.model_dump())
    except Exception:
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)

    if rule is None or rule.risk is not RiskLevel.CONSEQUENTIAL:
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)

    current = _checked_now(now)
    expires_at = current + CHALLENGE_LIFETIME
    challenge_id = generate_challenge_id()
    display_code = generate_display_code()
    salt = secrets.token_hex(DISPLAY_CODE_SALT_BYTES)

    draft = PendingConfirmationDraft(
        operation=checked_operation,
        challenge_id=challenge_id,
        display_code_hash=derive_display_code_hash(display_code, salt),
        display_code_salt=salt,
        policy_identity=identity,
        policy_version=policy.policy_version,
        required_risk=rule.risk,
        required_reason=decision.reason,
        expires_at=expires_at,
    )
    try:
        repository.create_pending(db, draft, now=current)
    except ConfirmationRecordError:
        return ChallengeIssueResult(ChallengeIssueOutcome.UNAVAILABLE)

    summary = build_operation_summary(
        checked_operation, description=rule.description, risk=rule.risk
    )
    return ChallengeIssueResult(
        ChallengeIssueOutcome.ISSUED,
        IssuedChallenge(
            challenge_id=challenge_id,
            summary=summary,
            display_code=display_code,
            expires_at=expires_at,
        ),
    )


def decide(
    db: Session,
    challenge_id: str,
    *,
    decision: ConfirmationDecision,
    display_code: str | None = None,
    policy: AuthorizationPolicy,
    executors: ExecutorRegistry,
    repository: AssistantConfirmationRepository | None = None,
    now: datetime | None = None,
) -> DecisionResult:
    """Apply one decision to one challenge and return a sanitized result.

    Consumption (for a confirmation) is committed before the executor is
    invoked, so a crash after the side effect cannot roll the consumption
    back and replay it. Every failure returns the same generic refusal and
    executes nothing.
    """
    repository = repository or AssistantConfirmationRepository()
    current = _checked_now(now)
    transition_time = None if now is None else current
    if decision is ConfirmationDecision.CANCEL:
        return _decide_terminal(
            db, repository, challenge_id, ConfirmationDecision.CANCEL, transition_time
        )
    if decision is ConfirmationDecision.REJECT:
        return _decide_terminal(
            db, repository, challenge_id, ConfirmationDecision.REJECT, transition_time
        )
    if decision is not ConfirmationDecision.CONFIRM:
        return DecisionResult(
            ConfirmationDecisionStatus.REFUSED, _GENERIC_REFUSAL_MESSAGE, False
        )
    return _confirm(
        db,
        challenge_id,
        display_code=display_code,
        policy=policy,
        executors=executors,
        repository=repository,
        now=current,
        transition_time=transition_time,
    )


def _refusal() -> DecisionResult:
    return DecisionResult(
        ConfirmationDecisionStatus.REFUSED, _GENERIC_REFUSAL_MESSAGE, False
    )


def _decide_terminal(
    db: Session,
    repository: AssistantConfirmationRepository,
    challenge_id: str,
    decision: ConfirmationDecision,
    transition_time: datetime | None,
) -> DecisionResult:
    cancelling = decision is ConfirmationDecision.CANCEL
    try:
        if cancelling:
            won = repository.cancel(db, challenge_id, now=transition_time)
        else:
            won = repository.reject(db, challenge_id, now=transition_time)
        db.commit()
    except Exception:
        db.rollback()
        return _refusal()
    if not won:
        return _refusal()
    if cancelling:
        return DecisionResult(
            ConfirmationDecisionStatus.CANCELLED, _CANCELLED_MESSAGE, False
        )
    return DecisionResult(ConfirmationDecisionStatus.REJECTED, _REJECTED_MESSAGE, False)


def _safe_invalidate(
    db: Session,
    repository: AssistantConfirmationRepository,
    challenge_id: str,
    current: datetime | None,
) -> None:
    try:
        repository.invalidate(db, challenge_id, now=current)
        db.commit()
    except Exception:
        db.rollback()


def _confirm(
    db: Session,
    challenge_id: str,
    *,
    display_code: str | None,
    policy: AuthorizationPolicy,
    executors: ExecutorRegistry,
    repository: AssistantConfirmationRepository,
    now: datetime,
    transition_time: datetime | None,
) -> DecisionResult:
    try:
        record = repository.lock_pending_for_update(db, challenge_id)
    except Exception:
        db.rollback()
        return _refusal()

    if record is None:
        db.rollback()
        return _refusal()

    try:
        if transition_time is None:
            expired = repository.expire_if_overdue(db, challenge_id, now=None)
        else:
            expired = record.expires_at <= transition_time
            if expired:
                repository.expire_if_overdue(db, challenge_id, now=transition_time)
        if expired:
            db.commit()
            return _refusal()
    except Exception:
        db.rollback()
        return _refusal()

    try:
        stored_operation = ProposedOperation(
            operation_id=record.operation_id,
            target=record.target,
            scope=record.scope,
            parameters=dict(record.parameters or {}),
        )
    except Exception:
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()

    if not verify_display_code(record, display_code):
        try:
            repository.record_failed_code_attempt(db, challenge_id, now=transition_time)
            db.commit()
        except Exception:
            db.rollback()
        return _refusal()

    try:
        identity = authorization_policy_identity(policy)
        scope = AuthorizedScope(
            operation_id=stored_operation.operation_id,
            target=stored_operation.target,
            scope=stored_operation.scope,
            parameters=dict(stored_operation.parameters),
        )
        decision_without_scope = evaluate_authorization(stored_operation, policy=policy)
        decision_with_scope = evaluate_authorization(
            stored_operation, policy=policy, authorized=scope
        )
    except Exception:
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()

    if identity != record.policy_identity:
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()
    if decision_without_scope.outcome is not AuthorizationOutcome.REQUIRE_CONFIRMATION:
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()
    if decision_with_scope.outcome is not AuthorizationOutcome.ALLOW:
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()
    if not scope.covers(stored_operation):
        _safe_invalidate(db, repository, challenge_id, transition_time)
        return _refusal()

    if executors.get(stored_operation.operation_id) is None:
        db.rollback()
        return DecisionResult(
            ConfirmationDecisionStatus.UNAVAILABLE, _UNAVAILABLE_MESSAGE, False
        )

    executor = executors.get(stored_operation.operation_id)
    try:
        consumed = repository.consume(
            db,
            challenge_id,
            expected_policy_identity=identity,
            now=transition_time,
        )
        if not consumed:
            db.commit()
            return _refusal()
        db.commit()
    except Exception:
        db.rollback()
        return _refusal()

    if executor is None:  # defensive: the check above already refused
        return _refusal()
    return _execute(
        db,
        repository,
        challenge_id,
        executor,
        stored_operation,
        scope,
    )


def _execute(
    db: Session,
    repository: AssistantConfirmationRepository,
    challenge_id: str,
    executor: Executor,
    operation: ProposedOperation,
    scope: AuthorizedScope,
) -> DecisionResult:
    outcome: ConfirmationOutcome
    try:
        result = executor(operation, scope)
    except ExecutorInterrupted:
        outcome = ConfirmationOutcome.UNKNOWN_AFTER_CONSUME
    except ExecutorError:
        outcome = ConfirmationOutcome.FAILED
    except Exception:
        outcome = ConfirmationOutcome.UNKNOWN_AFTER_CONSUME
    else:
        outcome = _outcome_for_result(result)

    try:
        recorded = repository.record_outcome(db, challenge_id, outcome)
        db.commit()
    except Exception:
        db.rollback()
        recorded = False

    return _result_for_outcome(outcome, recorded)


def _outcome_for_result(result: object) -> ConfirmationOutcome:
    if result is ExecutorResult.SUCCEEDED:
        return ConfirmationOutcome.SUCCEEDED
    if result is ExecutorResult.FAILED:
        return ConfirmationOutcome.FAILED
    return ConfirmationOutcome.UNKNOWN_AFTER_CONSUME


def _result_for_outcome(outcome: ConfirmationOutcome, recorded: bool) -> DecisionResult:
    if outcome is ConfirmationOutcome.SUCCEEDED and recorded:
        return DecisionResult(
            ConfirmationDecisionStatus.EXECUTED, _EXECUTED_MESSAGE, True
        )
    if outcome is ConfirmationOutcome.FAILED:
        return DecisionResult(ConfirmationDecisionStatus.FAILED, _FAILED_MESSAGE, True)
    return DecisionResult(ConfirmationDecisionStatus.UNKNOWN, _UNKNOWN_MESSAGE, True)


__all__ = [
    "CHALLENGE_ID_BYTES",
    "CHALLENGE_LIFETIME",
    "DISPLAY_CODE_ALPHABET",
    "DISPLAY_CODE_HASH_CONTEXT",
    "DISPLAY_CODE_LENGTH",
    "ChallengeIssueOutcome",
    "ChallengeIssueResult",
    "DecisionResult",
    "IssuedChallenge",
    "build_operation_summary",
    "decide",
    "derive_display_code_hash",
    "generate_challenge_id",
    "generate_display_code",
    "is_well_formed_display_code",
    "issue_challenge",
    "normalize_display_code",
    "verify_display_code",
]
