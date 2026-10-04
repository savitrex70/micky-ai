"""Focused CLI tests: entry point, dispatch, arguments, exit codes,
output contract, read-only behavior, and architecture boundaries.

The CLI is exercised end-to-end through its public entry point
(``rop.cli.main``) over an isolated in-memory database; service
delegation is proven behaviorally, not by mocking business logic.
No model, provider, API key, or network is involved.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401  (register all ORM models on Base)
from rop.cli import build_parser, main
from rop.database import Base

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run the CLI in-process and capture (exit_code, stdout, stderr).

    A ``SystemExit`` from argparse (help exits 0, usage errors exit 2)
    is converted into the same process exit code the shell observes.
    """
    stdout, stderr = io.StringIO(), io.StringIO()
    code: int
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = main(argv, session_factory=TestingSessionLocal)
        except SystemExit as exc:
            raw = exc.code
            if raw is None or raw is True:
                code = 0 if raw is None else 1
            elif isinstance(raw, int):
                code = raw
            else:
                code = 1
    return code, stdout.getvalue(), stderr.getvalue()


def run_cli_expect_ok(argv: list[str]) -> dict[str, Any]:
    code, out, err = run_cli(argv)
    assert code == 0, (code, out, err)
    assert err == ""
    return json.loads(out)


def run_cli_expect_usage_error(argv: list[str]) -> None:
    """Argparse usage errors exit 2 with a usage message on stderr."""
    code, out, err = run_cli(argv)
    assert code == 2, (code, out, err)
    assert "usage" in err
    assert out == ""


@pytest.fixture(autouse=True)
def _rop_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the required ROP_* settings for lazy application imports."""
    monkeypatch.setenv("ROP_APP_NAME", "Reasoning Operating Platform")
    monkeypatch.setenv("ROP_ENVIRONMENT", "testing")
    monkeypatch.setenv("ROP_LOG_LEVEL", "INFO")
    monkeypatch.setenv(
        "ROP_DATABASE_URL", "postgresql+psycopg://rop:rop@localhost:5432/rop"
    )


def _add_stable_observation(session_id: str, text: str) -> None:
    """Seed one observation so post-run exogenous inputs stay stable
    (matching the Task 127 canonical idempotency-test pattern)."""
    from rop.models import Observation

    with TestingSessionLocal() as db:
        db.add(
            Observation(
                session_id=UUID(session_id),
                text=text,
                type="symptom",
                confidence=0.95,
                source="rule_based",
            )
        )
        db.commit()


def seeded_session() -> str:
    """Create one session with a stable observation, returning its UUID."""
    created = run_cli_expect_ok(
        [
            "session",
            "create",
            "--domain",
            "testing",
            "--input",
            "Patient reports chest pain",
        ]
    )
    session_id = created["id"]
    assert UUID(session_id)
    _add_stable_observation(session_id, "Symptom = Chest pain")
    return str(session_id)


def _database_signature() -> dict[str, list[str]]:
    """Full read snapshot of every table, order-normalized."""
    signature: dict[str, list[str]] = {}
    with TestingSessionLocal() as db:
        for name, table in Base.metadata.tables.items():
            rows = db.execute(table.select()).fetchall()
            signature[name] = sorted(repr(tuple(row)) for row in rows)
    return signature


def _insert_malformed_receipt(session_id: str, fingerprint: str) -> None:
    """Insert a COMPLETED receipt the canonical projection must reject."""
    from rop.models import ReasoningRunReceipt

    with TestingSessionLocal() as db:
        db.add(
            ReasoningRunReceipt(
                session_id=UUID(session_id),
                input_fingerprint=fingerprint,
                exogenous_snapshot=["not-a-dict"],
                outcome="COMPLETED",
            )
        )
        db.commit()


def _build_snapshot(session_id: str) -> dict[str, Any]:
    from rop.services.reasoning_run_input_snapshot import (
        ReasoningRunInputSnapshotService,
    )

    with TestingSessionLocal() as db:
        return ReasoningRunInputSnapshotService().build_snapshot(db, UUID(session_id))


def _write_record_file(
    session_id: str,
    executed: dict[str, Any],
    snapshot: dict[str, Any],
) -> Path:
    """Write a replay record binding the executed result to the exact
    pre-execution snapshot the fingerprint was computed over."""
    record = {"original_result": executed, "original_snapshot": snapshot}
    path = Path(_REPOSITORY_ROOT) / f".cli_test_record_{uuid4().hex}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_top_level_help_lists_commands() -> None:
    code, out, err = run_cli(["--help"])
    assert code == 0
    assert err == ""
    for command in ("session", "run"):
        assert command in out
    assert "usage" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["session", "--help"],
        ["session", "create", "--help"],
        ["session", "get", "--help"],
        ["session", "list", "--help"],
        ["session", "delete", "--help"],
        ["run", "--help"],
        ["run", "execute", "--help"],
        ["run", "execute-idempotent", "--help"],
        ["run", "receipt", "--help"],
        ["run", "history", "--help"],
        ["run", "provenance-audit", "--help"],
        ["run", "replay", "--help"],
        ["run", "replay-audit", "--help"],
    ],
)
def test_every_help_path_starts_without_app_imports(argv: list[str]) -> None:
    """Help starts without reasoning and without touching the database."""
    code, out, err = run_cli(argv)
    assert code == 0
    assert err == ""
    assert "usage" in out


def test_every_advertised_command_is_dispatchable() -> None:
    """Every advertised command parses to a callable handler, and every
    service the CLI delegates to instantiates."""
    from rop.cli import _application_services

    minimal_valid_args: dict[tuple[str, str], list[str]] = {
        ("session", "create"): ["--domain", "testing", "--input", "text"],
        ("session", "get"): [str(uuid4())],
        ("session", "list"): [],
        ("session", "delete"): [str(uuid4())],
        ("run", "execute"): [str(uuid4())],
        ("run", "execute-idempotent"): [str(uuid4())],
        ("run", "receipt"): [str(uuid4()), "a" * 64],
        ("run", "history"): [str(uuid4())],
        ("run", "provenance-audit"): [str(uuid4())],
        ("run", "replay"): [str(uuid4()), "--record", "record.json"],
        ("run", "replay-audit"): [str(uuid4())],
    }
    parser = build_parser()
    for (group, name), extra in minimal_valid_args.items():
        parsed = parser.parse_args([group, name, *extra])
        assert callable(parsed.handler), f"{group} {name}"
    for name, service in vars(_application_services()).items():
        assert service is not None, name


def test_invalid_command_is_rejected_with_usage_error() -> None:
    run_cli_expect_usage_error(["definitely-not-a-command"])


def test_missing_subcommand_is_rejected_with_usage_error() -> None:
    run_cli_expect_usage_error([])
    run_cli_expect_usage_error(["session"])
    run_cli_expect_usage_error(["run"])


def test_malformed_uuid_is_rejected_as_usage_error() -> None:
    run_cli_expect_usage_error(["session", "get", "not-a-uuid"])


def test_malformed_fingerprint_is_rejected_as_usage_error() -> None:
    run_cli_expect_usage_error(["run", "receipt", str(uuid4()), "NOT-A-FP"])


@pytest.mark.parametrize("bad", ["A" * 64, "z" * 64, "a" * 63, "a" * 65, "g" * 64])
def test_fingerprint_must_be_lowercase_hex64(bad: str) -> None:
    run_cli_expect_usage_error(["run", "receipt", str(uuid4()), bad])


def test_missing_required_argument_is_rejected() -> None:
    run_cli_expect_usage_error(["session", "create", "--domain", "testing"])
    run_cli_expect_usage_error(["run", "replay", str(uuid4())])


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", '"text"'])
def test_invalid_metadata_json_is_rejected(bad: str) -> None:
    run_cli_expect_usage_error(
        [
            "session",
            "create",
            "--domain",
            "testing",
            "--input",
            "x",
            "--metadata",
            bad,
        ]
    )


@pytest.mark.parametrize("bad", ["0", "-1", "many"])
def test_invalid_limit_is_rejected(bad: str) -> None:
    run_cli_expect_usage_error(["session", "list", "--limit", bad])


@pytest.mark.parametrize("bad", ["-1", "many"])
def test_invalid_offset_is_rejected(bad: str) -> None:
    run_cli_expect_usage_error(["session", "list", "--offset", bad])


def test_session_create_get_list_delete_roundtrip() -> None:
    created = run_cli_expect_ok(
        [
            "session",
            "create",
            "--domain",
            "testing",
            "--input",
            "Patient reports chest pain",
            "--status",
            "active",
            "--stage",
            "observing",
            "--notes",
            "note",
            "--metadata",
            '{"source": "cli-test"}',
        ]
    )
    assert created["status"] == "active"
    assert created["domain"] == "testing"
    assert created["user_input"] == "Patient reports chest pain"
    assert created["current_stage"] == "observing"
    assert created["notes"] == "note"
    assert created["metadata"] == {"source": "cli-test"}

    fetched = run_cli_expect_ok(["session", "get", created["id"]])
    assert fetched == created

    listed = run_cli_expect_ok(["session", "list"])
    assert listed["count"] >= 1
    assert any(item["id"] == created["id"] for item in listed["sessions"])

    deleted = run_cli_expect_ok(["session", "delete", created["id"]])
    assert deleted == {"deleted": True, "session_id": created["id"]}

    code, out, err = run_cli(["session", "get", created["id"]])
    assert code == 1
    assert err.startswith("error: session ")
    assert err.rstrip().endswith("not found")
    assert out == ""


def test_session_delete_missing_returns_handled_failure() -> None:
    missing = str(uuid4())
    code, out, err = run_cli(["session", "delete", missing])
    assert code == 1
    assert err == f"error: session {missing} not found\n"
    assert out == ""


def test_run_commands_require_existing_session() -> None:
    missing = str(uuid4())
    for argv in (
        ["run", "execute", missing],
        ["run", "execute-idempotent", missing],
        ["run", "receipt", missing, "a" * 64],
        ["run", "history", missing],
        ["run", "provenance-audit", missing],
        ["run", "replay", missing, "--record", "whatever.json"],
        ["run", "replay-audit", missing],
    ):
        code, out, err = run_cli(argv)
        assert code == 1, argv
        assert err.startswith("error: session "), argv
        assert "not found" in err, argv
        assert out == "", argv


def test_receipt_found_false_for_unknown_identity() -> None:
    sid = seeded_session()
    result = run_cli_expect_ok(["run", "receipt", sid, "b" * 64])
    assert result["found"] is False
    assert result["receipt"] is None
    assert result["requested_session_id"] == sid
    assert result["requested_input_fingerprint"] == "b" * 64


def test_history_is_empty_before_any_run() -> None:
    sid = seeded_session()
    result = run_cli_expect_ok(["run", "history", sid])
    assert result["session_id"] == sid
    assert result["receipts"] == []


def test_provenance_audit_reports_empty_history() -> None:
    sid = seeded_session()
    result = run_cli_expect_ok(["run", "provenance-audit", sid])
    assert result["session_id"] == sid
    assert result["completed_receipts_examined"] == 0
    assert result["audit_consistent"] is True


def test_replay_audit_reports_no_material() -> None:
    sid = seeded_session()
    result = run_cli_expect_ok(["run", "replay-audit", sid])
    assert result["session_id"] == sid
    assert result["replay_state"] == "NO_MATERIAL"
    assert result["completed_receipts_examined"] == 0


def test_execute_then_receipt_history_and_provenance_audit() -> None:
    sid = seeded_session()
    executed = run_cli_expect_ok(["run", "execute", sid])
    assert executed["outcome"] == "COMPLETED"
    fingerprint = executed["input_fingerprint"]

    receipt = run_cli_expect_ok(["run", "receipt", sid, fingerprint])
    assert receipt["found"] is True
    assert receipt["receipt"]["input_fingerprint"] == fingerprint
    assert receipt["receipt"]["outcome"] == "COMPLETED"

    history = run_cli_expect_ok(["run", "history", sid])
    assert [item["input_fingerprint"] for item in history["receipts"]] == [fingerprint]

    audit = run_cli_expect_ok(["run", "provenance-audit", sid])
    assert audit["completed_receipts_examined"] == 1
    assert audit["audit_consistent"] is True

    # Deterministic rerun over unchanged inputs reports reuse and writes
    # no second receipt.
    before = run_cli_expect_ok(["run", "history", sid])
    reused = run_cli_expect_ok(
        ["run", "execute-idempotent", sid, "--known-fingerprint", fingerprint]
    )
    assert reused["disposition"] == "REUSED_IDENTICAL"
    assert run_cli_expect_ok(["run", "history", sid]) == before


def test_idempotent_execute_reports_stale_changed_deterministically() -> None:
    from rop.models import Observation

    sid = seeded_session()
    first = run_cli_expect_ok(["run", "execute-idempotent", sid])
    assert first["disposition"] == "EXECUTED_NEW"
    assert first["result"]["outcome"] == "COMPLETED"

    with TestingSessionLocal() as db:
        db.add(
            Observation(
                session_id=UUID(sid),
                text="Symptom = Chest pain",
                type="symptom",
                confidence=0.95,
                source="rule_based",
            )
        )
        db.commit()

    stale = run_cli_expect_ok(
        [
            "run",
            "execute-idempotent",
            sid,
            "--known-fingerprint",
            first["current_input_fingerprint"],
        ]
    )
    assert stale["disposition"] == "STALE_CHANGED"
    assert stale["result"] is None


def test_replay_is_deterministic_over_recorded_material() -> None:
    sid = seeded_session()
    snapshot = _build_snapshot(sid)
    executed = run_cli_expect_ok(["run", "execute", sid])
    record_path = _write_record_file(sid, executed, snapshot)
    try:
        first = run_cli_expect_ok(["run", "replay", sid, "--record", str(record_path)])
        second = run_cli_expect_ok(["run", "replay", sid, "--record", str(record_path)])
    finally:
        record_path.unlink(missing_ok=True)

    assert first == second
    assert first["original_input_fingerprint"] == executed["input_fingerprint"]
    assert isinstance(first["replay_consistent"], bool)
    assert isinstance(first["divergences"], list)
    assert first["replay_source"] == "REASONING_RUN_REPLAY_TASK_128"


def test_replay_record_file_must_exist_and_parse() -> None:
    sid = seeded_session()
    code, out, err = run_cli(["run", "replay", sid, "--record", "does-not-exist.json"])
    assert code == 1
    assert err.startswith("error: cannot read record file")
    assert out == ""

    bad = Path(_REPOSITORY_ROOT) / f".cli_test_bad_{uuid4().hex}.json"
    bad.write_text("{not json", encoding="utf-8")
    try:
        code, out, err = run_cli(["run", "replay", sid, "--record", str(bad)])
    finally:
        bad.unlink(missing_ok=True)
    assert code == 1
    assert err.startswith("error: record file is not valid JSON")
    assert out == ""


def test_replay_record_missing_keys_rejected() -> None:
    sid = seeded_session()
    record_path = Path(_REPOSITORY_ROOT) / f".cli_test_shape_{uuid4().hex}.json"
    record_path.write_text(json.dumps({"original_result": {}}), encoding="utf-8")
    try:
        code, out, err = run_cli(["run", "replay", sid, "--record", str(record_path)])
    finally:
        record_path.unlink(missing_ok=True)
    assert code == 1
    assert err.startswith("error: record file does not match the replay record")
    assert out == ""


def test_contract_failure_is_reported_not_traced() -> None:
    """An unreadable persisted receipt must surface as a concise handled
    error (exit 1), never a traceback and never fake success."""
    sid = seeded_session()
    fingerprint = "c" * 64
    _insert_malformed_receipt(sid, fingerprint)

    code, out, err = run_cli(["run", "receipt", sid, fingerprint])
    assert code == 1
    assert err.startswith("error: internal contract violation (RECEIPT_")
    assert out == ""
    assert "Traceback" not in err


def test_read_only_commands_write_nothing() -> None:
    """Read-only commands must not create records or mutate state."""
    sid = seeded_session()
    snapshot = _build_snapshot(sid)
    executed = run_cli_expect_ok(["run", "execute", sid])
    fingerprint = executed["input_fingerprint"]
    record_path = _write_record_file(sid, executed, snapshot)

    before = _database_signature()
    try:
        for argv in (
            ["run", "receipt", sid, fingerprint],
            ["run", "history", sid],
            ["run", "provenance-audit", sid],
            ["run", "replay-audit", sid],
            ["run", "replay", sid, "--record", str(record_path)],
            ["session", "get", sid],
            ["session", "list"],
        ):
            code, out, err = run_cli(argv)
            assert code == 0, (argv, err)
            assert err == ""
            assert _database_signature() == before, argv
    finally:
        record_path.unlink(missing_ok=True)


def test_output_is_deterministic_json_without_debug_noise() -> None:
    sid = seeded_session()
    result = run_cli_expect_ok(["run", "history", sid])
    again = run_cli_expect_ok(["run", "history", sid])
    assert again == result
    rendered = json.dumps(result, indent=2, sort_keys=True)
    assert rendered == json.dumps(again, indent=2, sort_keys=True)
    for forbidden in (
        "Traceback",
        "sqlalchemy",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
    ):
        assert forbidden.lower() not in rendered.lower(), forbidden


def test_missing_configuration_is_a_concise_error() -> None:
    """Without ROP_* configuration the CLI fails concisely, exit 1."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ROP_")}
    proc = subprocess.run(
        [sys.executable, "-m", "rop.cli", "session", "list"],
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPOSITORY_ROOT,
        timeout=120,
    )
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr.startswith("error: ROP configuration is missing")
    assert "Traceback" not in proc.stderr


def test_module_entry_point_subprocess() -> None:
    """``python -m rop.cli --help`` works in a fresh interpreter."""
    proc = subprocess.run(
        [sys.executable, "-m", "rop.cli", "--help"],
        capture_output=True,
        text=True,
        env={**os.environ},
        cwd=_REPOSITORY_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "usage" in proc.stdout
    assert "session" in proc.stdout
    assert "run" in proc.stdout


def test_no_provider_or_model_integration_in_cli() -> None:
    """Architecture boundary: the CLI ships exactly its two modules and
    contains no provider integration of any kind."""
    import rop.cli as cli_pkg

    package_dir = Path(cli_pkg.__file__).resolve().parent
    module_names = sorted(p.name for p in package_dir.glob("*.py"))
    assert module_names == ["__init__.py", "__main__.py"]
    source = "\n".join(p.read_text(encoding="utf-8") for p in package_dir.glob("*.py"))
    for forbidden in (
        "httpx",
        "requests",
        "ollama",
        "openai",
        "gemini",
        "anthropic",
        "api_key",
    ):
        assert forbidden.lower() not in source.lower(), forbidden
