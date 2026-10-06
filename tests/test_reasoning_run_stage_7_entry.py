"""Task 153: Stage 7 entry contract tests.

Covers the read-only Stage 7 entry evaluation over the canonical
deterministic core: healthy READY with no provider configured,
prohibited indicators blocking, missing boundary material unavailable,
generic test-only fakes staying legal, canonical Task 152 handoff
consumption, read-only behavior, determinism, and real-tree
architecture assertions. No model, no network, no concrete provider.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.schemas.reasoning_run_stage_7_entry import ReasoningRunStage7EntryRead
from rop.services import llm_reasoning as llm_reasoning_module
from rop.services.llm_reasoning import LLMReasoningService
from rop.services.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationContractError,
)
from rop.services.reasoning_run_stage_7_entry import (
    REASONING_RUN_STAGE_7_ENTRY_SOURCE_TASK_153,
    ReasoningRunStage7EntryService,
)

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(engine)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db() -> Generator[Session, None, None]:
    with TestingSessionLocal() as db:
        yield db


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

ENTRY_KEYS = {
    "stage_7_status",
    "boundary_available",
    "boundary_consistent",
    "provider_explicitly_injected",
    "concrete_provider_present",
    "network_integration_present",
    "api_key_configuration_present",
    "stage_7_source",
    "findings",
    "finding_count",
}


class _CertificationStub:
    """Records handoff calls and returns one fixed Stage 6 verdict."""

    def __init__(self, status: str) -> None:
        self._status = status
        self.calls: list[UUID] = []

    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        self.calls.append(session_id)
        return {"certification_status": self._status}


class _ContractErrorStub:
    def certify(self, db: Session, session_id: UUID) -> dict[str, object]:
        raise ReasoningRunStage6CertificationContractError("GATE_UNREADABLE", "forged")


class _RecordingProvider:
    provider_name = "recording"
    model_name = "recording-1"

    def generate_reasoning(self, request: object) -> object:
        from rop.services.llm_reasoning_provider import LLMReasoningProviderResponse

        return LLMReasoningProviderResponse(
            provider=self.provider_name,
            model=self.model_name,
            text="{}",
        )


@pytest.fixture(autouse=True)
def _reset_db() -> Generator[None, None, None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield


def _create_session(user_input: str = "Patient reports chest pain") -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "stage-7-entry-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def test_a_healthy_core_is_ready_with_no_provider() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        result = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))
    assert set(result) == ENTRY_KEYS
    assert result["stage_7_status"] == "READY"
    assert result["boundary_available"] is True
    assert result["boundary_consistent"] is True
    assert result["provider_explicitly_injected"] is True
    assert result["concrete_provider_present"] is False
    assert result["network_integration_present"] is False
    assert result["api_key_configuration_present"] is False
    assert result["findings"] == []
    assert result["finding_count"] == 0
    assert result["stage_7_source"] == REASONING_RUN_STAGE_7_ENTRY_SOURCE_TASK_153


def test_b_forged_concrete_provider_indicator_blocks(tmp_path) -> None:
    sid = _create_session()
    (tmp_path / ("rogue_" + "openai" + "_sdk.py")).write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "importer.py").write_text(
        "import " + "op" + "enai" + "\n", encoding="utf-8"
    )
    (tmp_path / "notes.py").write_text(
        "# mentions " + "op" + "enai" + " only in a comment\n", encoding="utf-8"
    )
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(production_root=str(tmp_path))
        result = service.evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "BLOCKED"
    assert result["concrete_provider_present"] is True
    module_findings = [
        f for f in result["findings"] if f.startswith("PROHIBITED_PROVIDER_MODULE:")
    ]
    indicator_findings = [
        f for f in result["findings"] if f.startswith("PROHIBITED_PROVIDER_INDICATOR:")
    ]
    assert len(module_findings) == 1
    assert "op" + "enai" in module_findings[0]
    assert len(indicator_findings) == 1
    assert indicator_findings[0].endswith(":1:op" + "enai")
    assert result["finding_count"] == len(result["findings"]) == 2
    assert all("notes.py" not in f for f in result["findings"])


def test_c_forged_credential_and_env_activation_block(tmp_path) -> None:
    sid = _create_session()
    (tmp_path / "configured.py").write_text(
        'API_KEY = "sk-forged-value"\n' 'PROVIDER = os.getenv("LLM_PROVIDER")\n',
        encoding="utf-8",
    )
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(production_root=str(tmp_path))
        result = service.evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "BLOCKED"
    assert result["api_key_configuration_present"] is True
    assert any(
        f == "PROHIBITED_API_KEY_INDICATOR:configured.py:1" for f in result["findings"]
    )
    assert any(
        f == "PROHIBITED_ENV_ACTIVATION_INDICATOR:configured.py:2"
        for f in result["findings"]
    )


def test_d_missing_boundary_material_is_unavailable() -> None:
    sid = _create_session()
    stub = _CertificationStub("CERTIFIED")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(
            certification_service=stub,
            boundary_modules=("rop.services.definitely_not_a_module",),
        )
        result = service.evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "UNAVAILABLE"
    assert result["boundary_available"] is False
    assert stub.calls == []
    assert (
        "BOUNDARY_MODULE_MISSING:rop.services.definitely_not_a_module"
        in result["findings"]
    )


def test_e_generic_test_only_provider_stays_legal(tmp_path) -> None:
    fake = _RecordingProvider()
    assert hasattr(fake, "provider_name")
    assert hasattr(fake, "model_name")
    assert callable(getattr(fake, "generate_reasoning", None))
    sid = _create_session()
    (tmp_path / "generic_provider.py").write_text(
        "class RecordingProvider:\n"
        '    provider_name = "recording"\n'
        '    model_name = "recording-1"\n'
        "\n"
        "    def generate_reasoning(self, request):\n"
        "        from rop.services.llm_reasoning_provider import (\n"
        "            LLMReasoningProviderResponse,\n"
        "        )\n"
        "\n"
        "        return LLMReasoningProviderResponse(\n"
        "            provider=self.provider_name,\n"
        "            model=self.model_name,\n"
        '            text="{}",\n'
        "        )\n",
        encoding="utf-8",
    )
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(production_root=str(tmp_path))
        result = service.evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "READY"
    assert result["concrete_provider_present"] is False
    assert result["findings"] == []


def test_f_consumes_canonical_stage_6_handoff_exactly_once() -> None:
    sid = _create_session()
    certified = _CertificationStub("CERTIFIED")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(certification_service=certified)
        result = service.evaluate(db, UUID(sid))
    assert certified.calls == [UUID(sid)]
    assert result["stage_7_status"] == "READY"

    no_material = _CertificationStub("NO_MATERIAL")
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(certification_service=no_material)
        result = service.evaluate(db, UUID(sid))
    assert no_material.calls == [UUID(sid)]
    assert result["stage_7_status"] == "READY"

    for refused_status in ("BLOCKED", "UNVERIFIABLE"):
        stub = _CertificationStub(refused_status)
        with TestingSessionLocal() as db:
            service = ReasoningRunStage7EntryService(certification_service=stub)
            result = service.evaluate(db, UUID(sid))
        assert stub.calls == [UUID(sid)]
        assert result["stage_7_status"] == "BLOCKED"
        assert f"STAGE_6_HANDOFF_NOT_CERTIFIED:{refused_status}" in result["findings"]


def _table_counts() -> dict[str, int]:
    with TestingSessionLocal() as db:
        return {
            table.name: db.execute(
                sql_text(f"SELECT COUNT(*) FROM {table.name}")
            ).scalar_one()
            for table in sorted(Base.metadata.sorted_tables, key=lambda t: t.name)
        }


def test_g_evaluation_is_read_only_and_executes_no_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _create_session()
    counts_before = _table_counts()

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Stage 7 entry evaluation must stay read-only")

    monkeypatch.setattr(Session, "add", _forbidden)
    monkeypatch.setattr(Session, "merge", _forbidden)
    monkeypatch.setattr(Session, "delete", _forbidden)
    monkeypatch.setattr(Session, "commit", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build", _forbidden)
    monkeypatch.setattr(LLMReasoningService, "build_for_session", _forbidden)

    with TestingSessionLocal() as db:
        result = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))

    assert result["stage_7_status"] == "READY"
    assert _table_counts() == counts_before


def test_h_evaluation_is_deterministic() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        first = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))
        second = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_i_real_tree_has_no_prohibited_integration() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        result = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))
    assert result["concrete_provider_present"] is False
    assert result["network_integration_present"] is False
    assert result["api_key_configuration_present"] is False
    assert result["boundary_consistent"] is True
    assert result["provider_explicitly_injected"] is True
    assert result["findings"] == []
    assert result["stage_7_status"] == "READY"


def test_handoff_contract_failure_is_unavailable() -> None:
    sid = _create_session()
    with TestingSessionLocal() as db:
        service = ReasoningRunStage7EntryService(
            certification_service=_ContractErrorStub()
        )
        result = service.evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "UNAVAILABLE"
    assert "STAGE_6_HANDOFF_UNAVAILABLE:GATE_UNREADABLE" in result["findings"]
    assert result["concrete_provider_present"] is False
    assert result["api_key_configuration_present"] is False


def test_provider_registry_violates_explicit_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid = _create_session()
    monkeypatch.setattr(
        llm_reasoning_module, "PROVIDER_REGISTRY", object(), raising=False
    )
    with TestingSessionLocal() as db:
        result = ReasoningRunStage7EntryService().evaluate(db, UUID(sid))
    assert result["stage_7_status"] == "BLOCKED"
    assert result["provider_explicitly_injected"] is False
    assert (
        "EXPLICIT_INJECTION_VIOLATION:registry_attribute:PROVIDER_REGISTRY"
        in result["findings"]
    )


def test_entry_schema_is_strict() -> None:
    valid = {
        "stage_7_status": "READY",
        "boundary_available": True,
        "boundary_consistent": True,
        "provider_explicitly_injected": True,
        "concrete_provider_present": False,
        "network_integration_present": False,
        "api_key_configuration_present": False,
        "stage_7_source": REASONING_RUN_STAGE_7_ENTRY_SOURCE_TASK_153,
        "findings": [],
        "finding_count": 0,
    }
    validated = ReasoningRunStage7EntryRead.model_validate(valid)
    assert validated.stage_7_status == "READY"
    with pytest.raises(ValidationError):
        ReasoningRunStage7EntryRead.model_validate({**valid, "winner": "model_a"})
    with pytest.raises(ValidationError):
        ReasoningRunStage7EntryRead.model_validate(
            {**valid, "stage_7_status": "CERTIFIED"}
        )
