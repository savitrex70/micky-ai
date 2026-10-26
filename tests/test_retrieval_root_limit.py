"""One retrieval request must never process an unbounded number of roots.

Empty or low-entry roots cost real filesystem work yet barely move the global
entry counter, so the root count has its own ceiling. These tests instrument the
work itself (root validation, identity captures, directory opens, ORM rows
materialized, and SQL statements) so they prove the bound, not just the constant.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.models  # noqa: F401
from rop import database as database_module
from rop.api import retrieval
from rop.database import Base
from rop.main import app
from rop.models.assistant_retrieval_root import AssistantRetrievalRoot
from rop.repositories.assistant_workspace import AssistantWorkspaceRepository
from rop.schemas.authorization import ProposedOperation
from rop.schemas.retrieval import (
    MAX_RETRIEVAL_ROOTS_PER_REQUEST,
    RetrievalSearchResponse,
)
from rop.services import local_paths, workspace_read

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"origin": ORIGIN, "content-type": "application/json"}
LIMIT = MAX_RETRIEVAL_ROOTS_PER_REQUEST

requires_backend = pytest.mark.skipif(
    not local_paths.secure_directory_traversal_supported(),
    reason="requires supported descriptor-relative retrieval primitives",
)


def _make_roots(
    base: Path, count: int, files: dict[int, str] | None = None
) -> list[tuple[str, str]]:
    """Create ``count`` real roots; ``files`` maps index -> text of note.md."""
    specs: list[tuple[str, str]] = []
    for index in range(count):
        root = base / f"root-{index:03d}"
        root.mkdir()
        if files and index in files:
            (root / "note.md").write_text(files[index], encoding="utf-8")
        identity = local_paths.local_directory_identity(root)
        assert identity is not None
        specs.append((str(root), identity))
    return specs


class _Work:
    """Counters for the per-root filesystem work done during one search."""

    def __init__(self) -> None:
        self.validations = 0
        self.identity_captures = 0
        self.directory_opens = 0


@pytest.fixture
def work(monkeypatch: pytest.MonkeyPatch) -> _Work:
    counts = _Work()
    safe_root = retrieval._safe_root
    identity = retrieval.local_directory_identity
    open_directory = retrieval.open_directory_descriptor

    def counted_safe_root(raw_path: str):
        counts.validations += 1
        return safe_root(raw_path)

    def counted_identity(path: Path):
        counts.identity_captures += 1
        return identity(path)

    def counted_open(path: Path):
        counts.directory_opens += 1
        return open_directory(path)

    monkeypatch.setattr(retrieval, "_safe_root", counted_safe_root)
    monkeypatch.setattr(retrieval, "local_directory_identity", counted_identity)
    monkeypatch.setattr(retrieval, "open_directory_descriptor", counted_open)
    return counts


@requires_backend
def test_many_empty_roots_never_exceed_the_root_limit(
    tmp_path: Path, work: _Work
) -> None:
    """Bare-path callers also pay for an identity capture per root; still bounded."""
    specs = _make_roots(tmp_path, LIMIT * 4)
    # Direct callers may pass bare strings, which makes _root_spec do filesystem
    # work. That work must be bounded too, not just the pinned-descriptor walk.
    bare_paths = [path for path, _ in specs]

    outcome = retrieval.search_roots_detailed(bare_paths, "needle", 10)

    assert outcome.matches == []
    assert outcome.roots_examined == LIMIT
    assert outcome.roots_skipped == LIMIT * 3
    assert work.validations == LIMIT
    assert work.identity_captures == LIMIT
    assert work.directory_opens <= LIMIT
    # Skipped roots are reported as roots, never as skipped files.
    assert outcome.skipped_files == 0


@requires_backend
def test_oversized_root_set_is_truthful_and_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, work: _Work
) -> None:
    monkeypatch.setattr(retrieval, "_MAX_ROOTS_PER_REQUEST", 5)
    specs = _make_roots(
        tmp_path,
        8,
        files={2: "inside needle", 6: "outside needle beyond the limit"},
    )

    first = retrieval.search_roots_detailed(list(specs), "needle", 10)
    second = retrieval.search_roots_detailed(list(specs), "needle", 10)

    assert first == second
    assert [match.path for match in first.matches] == [
        str(Path(specs[2][0]) / "note.md")
    ]
    assert all("beyond the limit" not in match.snippet for match in first.matches)
    assert first.roots_examined == 5
    assert first.roots_skipped == 3
    assert first.skipped_files == 0
    assert work.validations == 5 * 2


@requires_backend
def test_authorized_total_reports_roots_not_loaded_by_the_caller(
    tmp_path: Path,
) -> None:
    specs = _make_roots(tmp_path, 5, files={0: "needle"})

    outcome = retrieval.search_roots_detailed(
        list(specs), "needle", 10, authorized_total=12
    )

    assert outcome.roots_examined == 5
    assert outcome.roots_skipped == 7
    assert len(outcome.matches) == 1


@requires_backend
def test_global_work_limit_stop_is_reported_as_unsearched_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Roots never reached because another global ceiling fired are not hidden."""
    specs = _make_roots(tmp_path, 3)
    for path, _ in specs:
        for name in ("a.md", "b.md"):
            (Path(path) / name).write_text("no match", encoding="utf-8")
    monkeypatch.setattr(retrieval, "_MAX_FILES_PER_REQUEST", 3)

    outcome = retrieval.search_roots_detailed(list(specs), "needle", 10)

    assert outcome.files_examined == 3
    assert outcome.roots_examined == 2
    assert outcome.roots_skipped == 1
    assert outcome.roots_rejected == 0
    # The file ceiling skips one file; the never-reached root is reported
    # separately and is not added to skipped_files.
    assert outcome.skipped_files == 1


def test_unsupported_platform_reports_every_root_as_unsearched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieval, "secure_directory_traversal_supported", lambda: False
    )

    outcome = retrieval.search_roots_detailed(
        [("/a", "x"), ("/b", "y")], "needle", 10, authorized_total=9
    )

    assert outcome.matches == []
    assert outcome.roots_examined == 0
    assert outcome.roots_skipped == 9
    assert outcome.roots_rejected == 0
    # No file processing occurred, so no file may be reported as skipped.
    assert outcome.files_examined == 0
    assert outcome.skipped_files == 0


@requires_backend
def test_root_security_checks_still_apply_inside_the_bound(
    tmp_path: Path,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "secret.md").write_text("linked needle secret", encoding="utf-8")
    private_identity = local_paths.local_directory_identity(private)
    other = tmp_path / "other"
    other.mkdir()
    (other / "note.md").write_text("mismatched needle secret", encoding="utf-8")
    link = tmp_path / "link"
    try:
        link.symlink_to(private, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are unavailable")

    outcome = retrieval.search_roots_detailed(
        [
            (str(link), private_identity),  # symlinked root
            (str(other), private_identity),  # identity of a different directory
        ],
        "needle",
        10,
    )

    assert outcome.matches == []
    assert outcome.roots_examined == 2
    assert outcome.roots_rejected == 2
    assert outcome.roots_skipped == 0
    assert outcome.skipped_files == 0


def test_response_contract_keeps_existing_fields_and_defaults() -> None:
    response = RetrievalSearchResponse(
        query="q", matches=[], files_examined=1, skipped_files=2
    )

    assert response.roots_examined == 0
    assert response.roots_skipped == 0
    assert response.roots_limit == LIMIT
    assert LIMIT == 25
    with pytest.raises(ValueError):
        RetrievalSearchResponse(
            query="q",
            matches=[],
            files_examined=0,
            skipped_files=0,
            surprise=True,  # type: ignore[call-arg]
        )


@pytest.fixture
def session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def db_probe(
    session_factory: sessionmaker[Session],
) -> Generator[SimpleNamespace, None, None]:
    """Count root rows materialized by the ORM and the SQL that touched roots."""
    probe = SimpleNamespace(rows_loaded=0, statements=[])

    def on_load(_target: object, _context: object) -> None:
        probe.rows_loaded += 1

    def on_execute(_conn, _cursor, statement, _params, _context, _many) -> None:
        if "assistant_retrieval_roots" in statement.lower():
            probe.statements.append(statement)

    engine = session_factory.kw["bind"]
    event.listen(AssistantRetrievalRoot, "load", on_load)
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield probe
    finally:
        event.remove(AssistantRetrievalRoot, "load", on_load)
        event.remove(engine, "before_cursor_execute", on_execute)


def _persist(
    factory: sessionmaker[Session],
    specs: list[tuple[str, str | None]],
    *,
    identity: bool = True,
) -> None:
    """Insert roots with explicit, ascending creation times (deterministic order)."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with factory() as session:
        for index, (path, root_identity) in enumerate(specs):
            session.add(
                AssistantRetrievalRoot(
                    path=path,
                    root_identity=root_identity if identity else None,
                    created_at=base + timedelta(seconds=index),
                )
            )
        session.commit()


def test_repository_bounds_the_root_query_in_sql(
    session_factory: sessionmaker[Session],
    db_probe: SimpleNamespace,
    tmp_path: Path,
) -> None:
    surplus = 10
    specs = [(str(tmp_path / f"r{i:03d}"), "1:1:1") for i in range(LIMIT + surplus)]
    _persist(session_factory, specs)
    repository = AssistantWorkspaceRepository()
    db_probe.rows_loaded = 0
    db_probe.statements.clear()

    with session_factory() as session:
        roots = repository.list_roots(session)

    assert len(roots) == LIMIT
    # Only the bounded page was materialized; the surplus never left the database.
    assert db_probe.rows_loaded == LIMIT
    assert any("limit" in statement.lower() for statement in db_probe.statements)
    # Oldest first, so the same roots are chosen on every request.
    assert [root.path for root in roots] == [path for path, _ in specs[:LIMIT]]

    db_probe.rows_loaded = 0
    with session_factory() as session:
        assert len(repository.list_roots(session, limit=3)) == 3
        assert repository.count_roots(session) == LIMIT + surplus
        with pytest.raises(ValueError):
            repository.list_roots(session, limit=-1)
    assert db_probe.rows_loaded == 3  # counting loads no rows


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    http_client = TestClient(app, base_url=ORIGIN)
    try:
        yield http_client
    finally:
        http_client.close()


@requires_backend
def test_api_with_more_roots_than_the_limit_is_bounded_and_honest(
    client: TestClient,
    session_factory: sessionmaker[Session],
    db_probe: SimpleNamespace,
    tmp_path: Path,
    work: _Work,
) -> None:
    surplus = 10
    specs = _make_roots(
        tmp_path,
        LIMIT + surplus,
        files={0: "api-marker inside", LIMIT: "api-marker beyond the limit"},
    )
    _persist(session_factory, list(specs))
    db_probe.rows_loaded = 0
    db_probe.statements.clear()

    response = client.post(
        "/api/assistant/retrieval/search",
        headers=HEADERS,
        json={"query": "api-marker", "limit": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [match["path"] for match in body["matches"]] == [
        str(Path(specs[0][0]) / "note.md")
    ]
    assert "beyond the limit" not in response.text
    assert body["roots_examined"] == LIMIT
    assert body["roots_skipped"] == surplus
    assert body["roots_limit"] == LIMIT
    assert body["skipped_files"] == 0
    assert body["files_examined"] == 1
    # The bound holds at the database and at the filesystem.
    assert db_probe.rows_loaded == LIMIT
    selects = [s for s in db_probe.statements if "count(" not in s.lower()]
    assert len(selects) == 1 and "limit" in selects[0].lower()
    assert work.validations == LIMIT
    assert work.directory_opens <= LIMIT


@requires_backend
def test_api_handles_legacy_database_with_surplus_unidentified_roots(
    client: TestClient,
    session_factory: sessionmaker[Session],
    db_probe: SimpleNamespace,
    tmp_path: Path,
    work: _Work,
) -> None:
    surplus = 5
    specs = _make_roots(tmp_path, LIMIT + surplus, files={0: "legacy-marker"})
    _persist(session_factory, list(specs), identity=False)
    db_probe.rows_loaded = 0

    response = client.post(
        "/api/assistant/retrieval/search",
        headers=HEADERS,
        json={"query": "legacy-marker", "limit": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Unidentified legacy roots still fail closed, and the surplus is bounded.
    assert body["matches"] == []
    assert body["roots_examined"] == LIMIT
    assert body["roots_skipped"] == surplus
    assert db_probe.rows_loaded == LIMIT
    assert work.directory_opens == 0


@requires_backend
def test_chat_search_shares_the_bound_and_discloses_skipped_roots(
    session_factory: sessionmaker[Session],
    db_probe: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(retrieval, "_MAX_ROOTS_PER_REQUEST", 4)
    specs = _make_roots(
        tmp_path, 9, files={1: "chat-marker inside", 7: "chat-marker outside"}
    )
    _persist(session_factory, list(specs))
    db_probe.rows_loaded = 0

    result = workspace_read.run_workspace_read(
        ProposedOperation(
            operation_id="workspace_search_files",
            parameters={"query": "chat-marker"},
        )
    )

    assert "chat-marker inside" in result
    assert "chat-marker outside" not in result
    assert "found 1 matches" in result
    assert "5 authorized folder(s) were not searched" in result
    assert db_probe.rows_loaded == 4


@requires_backend
def test_missing_identity_root_is_rejected_not_a_skipped_file(
    tmp_path: Path,
) -> None:
    specs = _make_roots(tmp_path, 2, files={1: "needle"})

    outcome = retrieval.search_roots_detailed(
        [(specs[0][0], None), (specs[0][0], ""), specs[1]], "needle", 10
    )

    assert outcome.roots_examined == 3
    assert outcome.roots_rejected == 2
    assert outcome.roots_skipped == 0
    assert outcome.skipped_files == 0
    assert len(outcome.matches) == 1


@requires_backend
def test_stale_identity_root_is_rejected_not_a_skipped_file(
    tmp_path: Path,
) -> None:
    (first, identity), (second, _) = _make_roots(tmp_path, 2, files={0: "needle"})
    # A different directory presented with the first root's approved identity.
    outcome = retrieval.search_roots_detailed([(second, identity)], "needle", 10)

    assert outcome.roots_examined == 1
    assert outcome.roots_rejected == 1
    assert outcome.skipped_files == 0
    assert outcome.matches == []
    assert first != second


@requires_backend
def test_path_policy_rejection_is_counted_as_a_rejected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (good, good_identity), (blocked, blocked_identity) = _make_roots(
        tmp_path, 2, files={0: "needle", 1: "needle"}
    )
    network = retrieval._is_network_path
    monkeypatch.setattr(
        retrieval,
        "_is_network_path",
        lambda path: str(path).startswith(blocked) or network(path),
    )

    outcome = retrieval.search_roots_detailed(
        [(good, good_identity), (blocked, blocked_identity), ("relative/dir", "x")],
        "needle",
        10,
    )

    assert outcome.roots_examined == 3
    assert outcome.roots_rejected == 2  # network-policy root and relative path
    assert outcome.skipped_files == 0
    assert [m.path for m in outcome.matches] == [str(Path(good) / "note.md")]


@requires_backend
def test_failed_secure_open_is_a_rejected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = _make_roots(tmp_path, 1, files={0: "needle"})

    def failing_open(path: Path):
        raise OSError("cannot open securely")

    monkeypatch.setattr(retrieval, "open_directory_descriptor", failing_open)

    outcome = retrieval.search_roots_detailed(list(specs), "needle", 10)

    assert outcome.roots_examined == 1
    assert outcome.roots_rejected == 1
    assert outcome.roots_skipped == 0
    assert outcome.skipped_files == 0


@requires_backend
def test_rejected_unreached_and_searched_roots_never_double_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval, "_MAX_ROOTS_PER_REQUEST", 4)
    specs = _make_roots(tmp_path, 6, files={1: "needle"})
    specs[0] = (specs[0][0], None)  # rejected: no approved identity

    outcome = retrieval.search_roots_detailed(list(specs), "needle", 10)

    assert outcome.roots_examined == 4
    assert outcome.roots_rejected == 1
    assert outcome.roots_skipped == 2
    assert outcome.roots_examined + outcome.roots_skipped == 6
    assert outcome.skipped_files == 0
    assert outcome.files_examined == 1
    assert len(outcome.matches) == 1


@requires_backend
def test_successful_retrieval_reports_accurate_file_and_root_counts(
    tmp_path: Path,
) -> None:
    specs = _make_roots(tmp_path, 3, files={0: "alpha", 2: "needle here"})

    outcome = retrieval.search_roots_detailed(list(specs), "needle", 10)

    assert outcome.files_examined == 2
    assert outcome.skipped_files == 0
    assert outcome.roots_examined == 3
    assert outcome.roots_rejected == 0
    assert outcome.roots_skipped == 0
    assert len(outcome.matches) == 1


def test_response_contract_defaults_roots_rejected_to_zero() -> None:
    response = RetrievalSearchResponse(
        query="q", matches=[], files_examined=0, skipped_files=0
    )

    assert response.roots_rejected == 0


@requires_backend
def test_chat_search_reports_rejected_folders_separately_from_files(
    session_factory: sessionmaker[Session],
    db_probe: SimpleNamespace,
    tmp_path: Path,
) -> None:
    specs = _make_roots(tmp_path, 2, files={1: "chat-marker inside"})
    specs[0] = (specs[0][0], "stale-identity")
    _persist(session_factory, list(specs))

    result = workspace_read.run_workspace_read(
        ProposedOperation(
            operation_id="workspace_search_files",
            parameters={"query": "chat-marker"},
        )
    )

    assert "skipped 0 file(s)" in result
    assert "1 authorized folder(s) were not searched because they failed" in result
