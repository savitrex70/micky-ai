"""Deterministic command-line interface over the existing ROP services.

This package is a presentation layer only. Every command delegates to
the same application services the HTTP API uses; the CLI owns no
reasoning, persistence, fingerprint, receipt, replay, or audit logic
of its own. It validates arguments, opens exactly one database session
per invocation (closing it afterwards, never committing for read-only
commands), prints a deterministic JSON result, and keeps user-facing
failures concise:

- exit ``0``: the command succeeded;
- exit ``1``: a handled failure -- a missing resource or a
  deterministic internal contract violation -- reported as
  ``error: <explanation>`` on stderr with no traceback;
- exit ``2``: a usage error (argparse).

Unexpected internal failures are never disguised as success; they
propagate and terminate with a traceback. No model, provider, API key,
or network access is involved.

Entry point::

    python -m rop.cli --help

The module imports the application lazily, so ``--help`` works without
ROP_* configuration and without touching the database.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any
from uuid import UUID

from pydantic import ValidationError

__all__ = ["CliError", "build_parser", "main"]


class CliError(Exception):
    """A handled CLI failure reported as ``error: <message>`` with exit 1."""


_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

_EXIT_OK = 0
_EXIT_HANDLED_FAILURE = 1

_EPILOG = (
    "exit codes: 0 success; 1 handled failure (missing resource or "
    "deterministic contract violation); 2 usage error"
)


def _fingerprint_arg(value: str) -> str:
    """Validate a canonical 64-character lowercase SHA-256 fingerprint."""
    if _FINGERPRINT_RE.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "must be a 64-character lowercase hexadecimal SHA-256 fingerprint"
        )
    return value


def _metadata_arg(value: str) -> dict[str, Any]:
    """Validate a JSON object passed on the command line."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        raise argparse.ArgumentTypeError("must be valid JSON") from None
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("must be a JSON object")
    return parsed


def _positive_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _nonnegative_int_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer") from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser without importing the application."""
    parser = argparse.ArgumentParser(
        prog="rop.cli",
        description=(
            "Deterministic ROP command-line interface: a presentation "
            "layer over the existing application services."
        ),
        epilog=_EPILOG,
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{session,run}",
    )

    session = commands.add_parser(
        "session",
        help="manage reasoning sessions",
        description="Manage reasoning session records.",
        epilog=_EPILOG,
    )
    session_commands = session.add_subparsers(
        dest="session_command",
        required=True,
        metavar="{create,get,list,delete}",
    )

    session_create = session_commands.add_parser(
        "create",
        help="create a reasoning session",
        description="Create a reasoning session record.",
    )
    session_create.add_argument(
        "--domain",
        required=True,
        help="session domain, e.g. testing (required, non-empty)",
    )
    session_create.add_argument(
        "--input",
        required=True,
        help="free-text user input recorded on the session (required)",
    )
    session_create.add_argument(
        "--status",
        default="created",
        help="initial session status (default: created)",
    )
    session_create.add_argument(
        "--stage",
        default="initial",
        help="initial session stage (default: initial)",
    )
    session_create.add_argument(
        "--notes",
        default=None,
        help="optional free-text notes",
    )
    session_create.add_argument(
        "--metadata",
        type=_metadata_arg,
        default={},
        metavar="JSON",
        help="optional session metadata as a JSON object (default: {})",
    )
    session_create.set_defaults(handler=_session_create)

    session_get = session_commands.add_parser(
        "get",
        help="show one reasoning session",
        description="Print one reasoning session as JSON.",
    )
    session_get.add_argument(
        "session_id",
        type=_uuid_arg,
        help="session UUID",
    )
    session_get.set_defaults(handler=_session_get)

    session_list = session_commands.add_parser(
        "list",
        help="list reasoning sessions",
        description="List reasoning sessions, newest first, as JSON.",
    )
    session_list.add_argument(
        "--limit",
        type=_positive_int_arg,
        default=100,
        help="maximum number of sessions to return (default: 100)",
    )
    session_list.add_argument(
        "--offset",
        type=_nonnegative_int_arg,
        default=0,
        help="number of sessions to skip (default: 0)",
    )
    session_list.set_defaults(handler=_session_list)

    session_delete = session_commands.add_parser(
        "delete",
        help="delete one reasoning session",
        description="Delete one reasoning session and its owned records.",
    )
    session_delete.add_argument(
        "session_id",
        type=_uuid_arg,
        help="session UUID",
    )
    session_delete.set_defaults(handler=_session_delete)

    run = commands.add_parser(
        "run",
        help="deterministic reasoning-run commands",
        description=(
            "Execute, inspect, audit, and replay deterministic "
            "reasoning runs through the existing services."
        ),
        epilog=_EPILOG,
    )
    run_commands = run.add_subparsers(
        dest="run_command",
        required=True,
        metavar=(
            "{execute,execute-idempotent,receipt,history,"
            "provenance-audit,replay,replay-audit}"
        ),
    )

    run_execute = run_commands.add_parser(
        "execute",
        help="execute the deterministic reasoning workflow for a session",
        description=(
            "Run the established deterministic reasoning workflow "
            "end-to-end for one session (write-side orchestrator)."
        ),
    )
    run_execute.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_execute.set_defaults(handler=_run_execute)

    run_execute_idempotent = run_commands.add_parser(
        "execute-idempotent",
        help="execute once per input state, reusing identical completed runs",
        description=(
            "Idempotency-aware execution: EXECUTED_NEW, "
            "REUSED_IDENTICAL, or STALE_CHANGED are all valid "
            "deterministic results."
        ),
    )
    run_execute_idempotent.add_argument(
        "session_id", type=_uuid_arg, help="session UUID"
    )
    run_execute_idempotent.add_argument(
        "--known-fingerprint",
        type=_fingerprint_arg,
        default=None,
        metavar="FINGERPRINT",
        help=(
            "previously observed 64-character input fingerprint to "
            "compare against (optional)"
        ),
    )
    run_execute_idempotent.set_defaults(handler=_run_execute_idempotent)

    run_receipt = run_commands.add_parser(
        "receipt",
        help="inspect one exact completed reasoning-run receipt (read-only)",
        description=(
            "Inspect the exact canonical completed receipt identity "
            "(session, fingerprint). A valid but nonexistent identity "
            "is a normal result with found=false."
        ),
    )
    run_receipt.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_receipt.add_argument(
        "fingerprint",
        type=_fingerprint_arg,
        metavar="FINGERPRINT",
        help="64-character lowercase hexadecimal input fingerprint",
    )
    run_receipt.set_defaults(handler=_run_receipt)

    run_history = run_commands.add_parser(
        "history",
        help="list one session's completed reasoning-run receipts (read-only)",
        description=(
            "Read-only deterministic reasoning-run history for one " "session."
        ),
    )
    run_history.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_history.set_defaults(handler=_run_history)

    run_provenance_audit = run_commands.add_parser(
        "provenance-audit",
        help="audit one session's receipts for provenance consistency (read-only)",
        description=(
            "Read-only provenance consistency audit of every persisted "
            "COMPLETED receipt for one session."
        ),
    )
    run_provenance_audit.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_provenance_audit.set_defaults(handler=_run_provenance_audit)

    run_replay = run_commands.add_parser(
        "replay",
        help="replay a recorded run and report divergence (read-only)",
        description=(
            "Evaluate a recorded original execution result against the "
            "current session state. The record file must contain the "
            'JSON object {"original_result": {...}, "original_snapshot":'
            " {...}}. Divergence is a reported finding, not a failure."
        ),
    )
    run_replay.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_replay.add_argument(
        "--record",
        required=True,
        metavar="FILE",
        help="path to the recorded replay material (JSON)",
    )
    run_replay.set_defaults(handler=_run_replay)

    run_replay_audit = run_commands.add_parser(
        "replay-audit",
        help="audit one session's persisted replay material (read-only)",
        description=(
            "Read-only consistency audit of the replay-related receipt "
            "material persisted for one session."
        ),
    )
    run_replay_audit.add_argument("session_id", type=_uuid_arg, help="session UUID")
    run_replay_audit.set_defaults(handler=_run_replay_audit)

    return parser


def _uuid_arg(value: str) -> UUID:
    """Parse a UUID argument so malformed values fail as usage errors."""
    try:
        return UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid UUID value: {value!r}") from None


def _session_read(session: Any) -> dict[str, Any]:
    """Serialize one session through the canonical API read schema."""
    from rop.schemas import ReasoningSessionRead

    return ReasoningSessionRead.model_validate(session).model_dump(mode="json")


def _require_session(sessions: Any, db: Any, session_id: Any) -> None:
    """Mirror the API's session-existence check for every session command."""
    if sessions.get(db, session_id) is None:
        raise CliError(f"session {session_id} not found")


def _session_create(args: Any, db: Any, services: Any) -> dict[str, Any]:
    from rop.schemas import ReasoningSessionCreate

    try:
        data = ReasoningSessionCreate(
            status=args.status,
            domain=args.domain,
            user_input=args.input,
            current_stage=args.stage,
            notes=args.notes,
            metadata=args.metadata,
        )
    except ValidationError as exc:
        raise CliError(
            f"invalid session input: {_first_validation_message(exc)}"
        ) from exc
    created = services.sessions.create(db, data)
    return _session_read(created)


def _session_get(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    session = services.sessions.get(db, args.session_id)
    return _session_read(session)


def _session_list(args: Any, db: Any, services: Any) -> dict[str, Any]:
    sessions = services.sessions.list(db, offset=args.offset, limit=args.limit)
    return {
        "count": len(sessions),
        "offset": args.offset,
        "limit": args.limit,
        "sessions": [_session_read(session) for session in sessions],
    }


def _session_delete(args: Any, db: Any, services: Any) -> dict[str, Any]:
    if not services.sessions.delete(db, args.session_id):
        raise CliError(f"session {args.session_id} not found")
    return {"deleted": True, "session_id": str(args.session_id)}


def _run_execute(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.execution.execute_for_session(db, args.session_id)


def _run_execute_idempotent(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.idempotency.execute_idempotent(
        db,
        args.session_id,
        known_input_fingerprint=args.known_fingerprint,
    )


def _run_receipt(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.receipts.inspect(db, args.session_id, args.fingerprint)


def _run_history(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.receipts.history(db, args.session_id)


def _run_provenance_audit(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.receipt_provenance_audit.audit(db, args.session_id)


def _run_replay(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    record = _load_replay_record(args.record)
    return services.replay.replay(
        db,
        args.session_id,
        original_result=record["original_result"],
        original_snapshot=record["original_snapshot"],
    )


def _run_replay_audit(args: Any, db: Any, services: Any) -> dict[str, Any]:
    _require_session(services.sessions, db, args.session_id)
    return services.replay_consistency_audit.audit(db, args.session_id)


def _load_replay_record(path: str) -> dict[str, Any]:
    """Load and validate the recorded replay material file."""
    from rop.schemas import ReasoningRunReplayRequest

    try:
        with open(path, encoding="utf-8") as handle:
            parsed = json.load(handle)
    except OSError:
        raise CliError(f"cannot read record file: {path}") from None
    except json.JSONDecodeError:
        raise CliError(f"record file is not valid JSON: {path}") from None
    try:
        request = ReasoningRunReplayRequest.model_validate(parsed)
    except ValidationError as exc:
        raise CliError(
            f"record file does not match the replay record schema: "
            f"{_first_validation_message(exc)}"
        ) from exc
    return request.model_dump()


def _first_validation_message(exc: Any) -> str:
    """Render a compact, deterministic first-error message."""
    try:
        error = exc.errors()[0]
    except (AttributeError, IndexError):
        return str(exc)
    location = ".".join(str(part) for part in error.get("loc", ()))
    message = error.get("msg", "")
    return f"{location}: {message}" if location else message


def _application_services() -> Any:
    """Instantiate the existing application services the CLI delegates to."""
    from types import SimpleNamespace

    from rop.services import (
        ReasoningRunExecutionService,
        ReasoningRunIdempotencyService,
        ReasoningRunReceiptProvenanceAuditService,
        ReasoningRunReceiptService,
        ReasoningRunReplayConsistencyAuditService,
        ReasoningRunReplayService,
        ReasoningSessionService,
    )

    return SimpleNamespace(
        sessions=ReasoningSessionService(),
        execution=ReasoningRunExecutionService(),
        idempotency=ReasoningRunIdempotencyService(),
        receipts=ReasoningRunReceiptService(),
        receipt_provenance_audit=ReasoningRunReceiptProvenanceAuditService(),
        replay=ReasoningRunReplayService(),
        replay_consistency_audit=ReasoningRunReplayConsistencyAuditService(),
    )


def _contract_error_invariants() -> tuple[type[Exception], ...]:
    """Import the deterministic contract-error vocabulary to translate."""
    from rop.services import (
        ReasoningRunExecutionContractError,
        ReasoningRunIdempotencyContractError,
        ReasoningRunReceiptContractError,
        ReasoningRunReceiptProvenanceAuditContractError,
        ReasoningRunReplayConsistencyAuditContractError,
        ReasoningRunReplayContractError,
    )

    return (
        ReasoningRunExecutionContractError,
        ReasoningRunIdempotencyContractError,
        ReasoningRunReceiptContractError,
        ReasoningRunReceiptProvenanceAuditContractError,
        ReasoningRunReplayContractError,
        ReasoningRunReplayConsistencyAuditContractError,
    )


def _execute(args: Any, session_factory: Any) -> dict[str, Any]:
    """Run one command against one database session, closing it after."""
    try:
        from rop.database import SessionLocal

        services = _application_services()
    except ValidationError:
        raise CliError(
            "ROP configuration is missing or invalid; set the ROP_* "
            "environment variables or create a .env file (see .env.example)"
        ) from None

    factory = session_factory if session_factory is not None else SessionLocal
    db = factory()
    try:
        try:
            return args.handler(args, db, services)
        except _contract_error_invariants() as exc:
            raise CliError(
                f"internal contract violation ({getattr(exc, 'invariant', '')})"
            ) from exc
    finally:
        db.close()


def _render_json(result: dict[str, Any]) -> str:
    """Render a service result as deterministic JSON.

    Services return plain dicts whose identifiers are usually already
    strings; any residual non-JSON scalar (e.g. a raw ``UUID`` the HTTP
    layer would coerce through its response models) is rendered with
    its canonical ``str`` form, which is deterministic.
    """
    return json.dumps(result, indent=2, sort_keys=True, default=str)


def main(
    argv: list[str] | None = None,
    session_factory: Any = None,
) -> int:
    """Run one CLI command; return the process exit code.

    ``session_factory`` is an injection seam for tests; production
    always uses ``rop.database.SessionLocal``.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = _execute(args, session_factory)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_HANDLED_FAILURE
    print(_render_json(result))
    return _EXIT_OK
