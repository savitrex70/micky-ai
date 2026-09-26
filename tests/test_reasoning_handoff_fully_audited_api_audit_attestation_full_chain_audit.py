"""Tests for Task 090 full-chain audit of Tasks 055-088.

Independent end-to-end audit of the complete reasoning-handoff
chain from the Tasks 055-082 foundation through Tasks 083-088.
Test layer only; no production behavior is changed. Every artifact
is produced by the real canonical services; no contract logic is
duplicated here.
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Generator, Mapping
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle as mod085,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package as mod083,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response as mod087,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation import (
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    _expected_bundle_fingerprint as _expected_085_bundle_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    _expected_final_fingerprint as _expected_081_final_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    _expected_package_fingerprint as _expected_083_package_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    _expected_package_fingerprint as _expected_073_package_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075,
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_079,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    _expected_bundle_fingerprint as _expected_079_bundle_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_078,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_response_package_consistency import (  # noqa: E501
    _expected_package_fingerprint as _expected_077_package_fp,
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


@pytest.fixture(autouse=True)
def _ensure_own_db_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    yield


_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


def _create_session(user_input: str) -> str:
    resp = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-090-test"},
        },
    )
    assert resp.status_code == 201
    return str(resp.json()["id"])


def _seed_full(user_input: str) -> str:
    sid = _create_session(user_input)
    resp = client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    assert resp.status_code in (200, 201)
    resp = client.post(f"/sessions/{sid}/generate-candidates")
    assert resp.status_code in (200, 201)
    resp = client.post(f"/sessions/{sid}/evaluate-evidence")
    assert resp.status_code in (200, 201)
    return sid


def _build_full_chain(sid_str: str) -> dict[str, Any]:
    """Build every level with only real canonical services."""
    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        response_075 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    consistency_076 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService().build(  # noqa: E501
        response=response_075
    )
    package_077 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        attestation_response=response_075,
        attestation_response_consistency=consistency_076,
    )
    consistency_078 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=package_077
    )
    bundle_079 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=package_077,
        response_package_consistency=consistency_078,
    )
    consistency_080 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=bundle_079
    )
    final_081 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=bundle_079,
        response_bundle_consistency=consistency_080,
    )
    consistency_082 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService().build(  # noqa: E501
        final_attestation=final_081
    )
    package_083 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build(  # noqa: E501
        session_id=sid,
        final_attestation=final_081,
        final_attestation_consistency=consistency_082,
    )
    consistency_084 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
        package=package_083
    )
    bundle_085 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build(  # noqa: E501
        session_id=sid,
        final_attestation_package=package_083,
        final_attestation_package_consistency=consistency_084,
    )
    consistency_086 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
        bundle=bundle_085
    )
    with TestingSessionLocal() as db:
        response_087 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    result_088 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=response_087
    )
    return {
        "sid_str": sid_str,
        "response_075": response_075,
        "consistency_076": consistency_076,
        "package_077": package_077,
        "consistency_078": consistency_078,
        "bundle_079": bundle_079,
        "consistency_080": consistency_080,
        "final_081": final_081,
        "consistency_082": consistency_082,
        "package_083": package_083,
        "consistency_084": consistency_084,
        "bundle_085": bundle_085,
        "consistency_086": consistency_086,
        "response_087": response_087,
        "result_088": result_088,
    }


def _seed_and_build() -> dict[str, Any]:
    sid_str = _seed_full("Task 090 full chain capture")
    return _build_full_chain(sid_str)


def _collect_session_ids(value: Any, acc: list[Any]) -> None:
    if isinstance(value, Mapping):
        if "session_id" in value:
            acc.append(value["session_id"])
        for item in value.values():
            _collect_session_ids(item, acc)
    elif isinstance(value, list):
        for item in value:
            _collect_session_ids(item, acc)


def _collect_fingerprint_pairs(value: Any, acc: list[tuple[str, Any]]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, str) and key.endswith("_fingerprint"):
                acc.append((key, item))
        for item in value.values():
            _collect_fingerprint_pairs(item, acc)
    elif isinstance(value, list):
        for item in value:
            _collect_fingerprint_pairs(item, acc)


def _collect_mappings(value: Any, acc: list[Mapping[str, Any]]) -> None:
    if isinstance(value, Mapping):
        acc.append(value)
        for item in value.values():
            _collect_mappings(item, acc)
    elif isinstance(value, list):
        for item in value:
            _collect_mappings(item, acc)


def test_full_chain_valid_and_088_consistent() -> None:
    chain = _seed_and_build()
    response_087 = chain["response_087"]
    result_088 = chain["result_088"]
    assert response_087["available"] is True
    assert response_087["response_consistent"] is True
    assert result_088["available"] is True
    assert result_088["response_consistent"] is True
    assert result_088["consistency_issues"] == []
    assert (
        result_088["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )


def test_session_identity_bound_through_every_level() -> None:
    chain = _seed_and_build()
    sid_str = chain["sid_str"]
    expected = str(UUID(sid_str))
    collected: list[Any] = []
    _collect_session_ids(chain["response_087"], collected)
    assert len(collected) >= 8
    for raw in collected:
        assert str(raw) == expected
    nested: list[Any] = []
    _collect_session_ids(chain["package_077"], nested)
    for raw in nested:
        assert str(raw) == expected
    deep: list[Any] = []
    _collect_session_ids(chain["bundle_085"], deep)
    for raw in deep:
        assert str(raw) == expected


def test_every_fixed_source_identifier_correct() -> None:
    chain = _seed_and_build()
    response_075 = chain["response_075"]
    package_073 = response_075["attestation_package"]
    assert (
        package_073["attestation"]["attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_SOURCE_TASK_071
    )
    assert (
        package_073["attestation_consistency"]["attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_CONSISTENCY_SOURCE_TASK_072  # noqa: E501
    )
    assert (
        package_073["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_SOURCE_TASK_073  # noqa: E501
    )
    assert (
        response_075["attestation_package_consistency"]["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_074  # noqa: E501
    )
    assert (
        response_075["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_SOURCE_TASK_075  # noqa: E501
    )
    assert (
        chain["consistency_076"]["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_076  # noqa: E501
    )
    assert (
        chain["package_077"]["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_077  # noqa: E501
    )
    assert (
        chain["consistency_078"]["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_078  # noqa: E501
    )
    assert (
        chain["bundle_079"]["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_079  # noqa: E501
    )
    assert (
        chain["consistency_080"]["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_080  # noqa: E501
    )
    assert (
        chain["final_081"]["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_SOURCE_TASK_081  # noqa: E501
    )
    assert (
        chain["consistency_082"]["final_attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_082  # noqa: E501
    )
    assert (
        chain["package_083"]["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083  # noqa: E501
    )
    assert (
        chain["consistency_084"]["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084  # noqa: E501
    )
    assert (
        chain["bundle_085"]["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085  # noqa: E501
    )
    assert (
        chain["consistency_086"]["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086  # noqa: E501
    )
    assert (
        chain["response_087"]["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087  # noqa: E501
    )
    assert (
        chain["result_088"]["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088  # noqa: E501
    )


def test_every_fingerprint_is_lowercase_sha256() -> None:
    chain = _seed_and_build()
    pairs: list[tuple[str, Any]] = []
    _collect_fingerprint_pairs(chain["response_087"], pairs)
    assert len(pairs) >= 10
    for _key, value in pairs:
        assert isinstance(value, str)
        assert _FINGERPRINT_RE.fullmatch(value) is not None
    audit_pairs: list[tuple[str, Any]] = []
    _collect_fingerprint_pairs(chain["result_088"], audit_pairs)
    for _key, value in audit_pairs:
        assert isinstance(value, str)
        assert _FINGERPRINT_RE.fullmatch(value) is not None


def test_audited_fingerprints_equal_siblings() -> None:
    chain = _seed_and_build()
    envelop: list[Mapping[str, Any]] = []
    _collect_mappings(chain["response_087"], envelop)
    checked = 0
    for mapping in envelop:
        if "package_fingerprint" in mapping and (
            "audited_package_fingerprint" in mapping
        ):
            assert (
                mapping["audited_package_fingerprint"] == mapping["package_fingerprint"]
            )
            checked += 1
        if "bundle_fingerprint" in mapping and (
            "audited_bundle_fingerprint" in mapping
        ):
            assert (
                mapping["audited_bundle_fingerprint"] == mapping["bundle_fingerprint"]
            )
            checked += 1
        if "final_attestation_fingerprint" in mapping and (
            "audited_final_attestation_fingerprint" in mapping
        ):
            assert (
                mapping["audited_final_attestation_fingerprint"]
                == mapping["final_attestation_fingerprint"]
            )
            checked += 1
    assert checked >= 10


def test_fingerprints_independently_recomputable() -> None:
    chain = _seed_and_build()
    package_073 = chain["response_075"]["attestation_package"]
    assert _expected_073_package_fp(package_073) == package_073["package_fingerprint"]
    assert (
        _expected_073_package_fp(package_073)
        == package_073["audited_package_fingerprint"]
    )
    assert (
        _expected_077_package_fp(chain["package_077"])
        == chain["package_077"]["package_fingerprint"]
    )
    assert (
        _expected_077_package_fp(chain["package_077"])
        == chain["package_077"]["audited_package_fingerprint"]
    )
    assert (
        _expected_079_bundle_fp(chain["bundle_079"])
        == chain["bundle_079"]["bundle_fingerprint"]
    )
    assert (
        _expected_079_bundle_fp(chain["bundle_079"])
        == chain["bundle_079"]["audited_bundle_fingerprint"]
    )
    assert (
        _expected_081_final_fp(chain["final_081"])
        == chain["final_081"]["final_attestation_fingerprint"]
    )
    assert (
        _expected_081_final_fp(chain["final_081"])
        == chain["final_081"]["audited_final_attestation_fingerprint"]
    )
    assert (
        _expected_083_package_fp(chain["package_083"])
        == chain["package_083"]["package_fingerprint"]
    )
    assert (
        _expected_083_package_fp(chain["package_083"])
        == chain["package_083"]["audited_package_fingerprint"]
    )
    assert (
        _expected_085_bundle_fp(chain["bundle_085"])
        == chain["bundle_085"]["bundle_fingerprint"]
    )
    assert (
        _expected_085_bundle_fp(chain["bundle_085"])
        == chain["bundle_085"]["audited_bundle_fingerprint"]
    )


def test_legitimate_defect_propagates_with_refreshed_prints() -> None:
    chain = _seed_and_build()
    sid = UUID(chain["sid_str"])
    response_075 = chain["response_075"]
    consistency_076 = chain["consistency_076"]
    defective_076 = copy.deepcopy(consistency_076)
    defective_076["consistency_issues"] = ["RESPONSE_RELATIONSHIP_MISMATCH"]
    defective_076["response_consistent"] = False
    defective_076["response_relationship_consistent"] = False
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService._validate_result(  # noqa: E501
        defective_076
    )
    defective_077 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        attestation_response=response_075,
        attestation_response_consistency=defective_076,
    )
    assert defective_077["available"] is True
    assert defective_077["package_consistent"] is False
    assert (
        _expected_077_package_fp(defective_077) == defective_077["package_fingerprint"]
    )
    defective_078 = ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=defective_077
    )
    defective_079 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=defective_077,
        response_package_consistency=defective_078,
    )
    assert defective_079["bundle_consistent"] is False
    assert _expected_079_bundle_fp(defective_079) == defective_079["bundle_fingerprint"]
    defective_080 = ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=defective_079
    )
    defective_081 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=defective_079,
        response_bundle_consistency=defective_080,
    )
    assert defective_081["final_attestation_consistent"] is False
    defective_082 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService().build(  # noqa: E501
        final_attestation=defective_081
    )
    defective_083 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build(  # noqa: E501
        session_id=sid,
        final_attestation=defective_081,
        final_attestation_consistency=defective_082,
    )
    # AND-derivation (Tasks 077/079/081 family pattern): the package binds
    # the verified artifact verdict AND the verified audit verdict, so a
    # defect truthfully reported anywhere upstream stays visible here.
    assert defective_083["package_consistent"] is False
    assert defective_083["final_attestation"]["final_attestation_consistent"] is False
    assert (
        _expected_083_package_fp(defective_083) == defective_083["package_fingerprint"]
    )
    defective_084 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
        package=defective_083
    )
    defective_085 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build(  # noqa: E501
        session_id=sid,
        final_attestation_package=defective_083,
        final_attestation_package_consistency=defective_084,
    )
    assert defective_085["bundle_consistent"] is False
    assert (
        defective_085["final_attestation_package"]["final_attestation"][
            "final_attestation_consistent"
        ]
        is False
    )
    assert _expected_085_bundle_fp(defective_085) == defective_085["bundle_fingerprint"]
    defective_086 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
        bundle=defective_085
    )
    defective_response = copy.deepcopy(chain["response_087"])
    defective_response["final_attestation_bundle"] = defective_085
    defective_response["final_attestation_bundle_consistency"] = defective_086
    defective_response["response_consistent"] = bool(
        defective_086.get("bundle_consistent", False)
    )
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=defective_response
    )
    assert audit["available"] is True
    assert defective_085["bundle_consistent"] is False
    assert defective_083["package_consistent"] is False
    assert defective_077["package_consistent"] is False
    assert defective_081["final_attestation_consistent"] is False
    assert audit["consistency_issues"] == []
    assert audit["response_consistent"] is True


def test_tampered_source_flagged_by_top_audit() -> None:
    chain = _seed_and_build()
    tampered = copy.deepcopy(chain["response_087"])
    tampered["final_attestation_bundle"] = copy.deepcopy(
        chain["response_087"]["final_attestation_bundle"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"] = copy.deepcopy(
        chain["response_087"]["final_attestation_bundle"]["final_attestation_package"]
    )
    tampered["final_attestation_bundle"]["final_attestation_package"][
        "package_source"
    ] = "WRONG"
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered
    )
    assert audit["response_consistent"] is False
    assert audit["source_consistency"] is False
    assert "PACKAGE_SOURCE_MISMATCH" in audit["consistency_issues"]
    source_issues = [
        issue
        for issue in audit["consistency_issues"]
        if issue.endswith("_SOURCE_MISMATCH")
    ]
    assert source_issues == ["PACKAGE_SOURCE_MISMATCH"]


def test_inputs_not_mutated() -> None:
    chain = _seed_and_build()
    sid = UUID(chain["sid_str"])
    before_075 = copy.deepcopy(chain["response_075"])
    before_076 = copy.deepcopy(chain["consistency_076"])
    before_077 = copy.deepcopy(chain["package_077"])
    before_078 = copy.deepcopy(chain["consistency_078"])
    before_079 = copy.deepcopy(chain["bundle_079"])
    before_080 = copy.deepcopy(chain["consistency_080"])
    before_081 = copy.deepcopy(chain["final_081"])
    before_082 = copy.deepcopy(chain["consistency_082"])
    before_083 = copy.deepcopy(chain["package_083"])
    before_084 = copy.deepcopy(chain["consistency_084"])
    before_085 = copy.deepcopy(chain["bundle_085"])
    before_086 = copy.deepcopy(chain["consistency_086"])
    before_087 = copy.deepcopy(chain["response_087"])
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyService().build(  # noqa: E501
        response=chain["response_075"]
    )
    assert chain["response_075"] == before_075
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        attestation_response=chain["response_075"],
        attestation_response_consistency=chain["consistency_076"],
    )
    assert chain["response_075"] == before_075
    assert chain["consistency_076"] == before_076
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=chain["package_077"]
    )
    assert chain["package_077"] == before_077
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=chain["package_077"],
        response_package_consistency=chain["consistency_078"],
    )
    assert chain["package_077"] == before_077
    assert chain["consistency_078"] == before_078
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=chain["bundle_079"]
    )
    assert chain["bundle_079"] == before_079
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=chain["bundle_079"],
        response_bundle_consistency=chain["consistency_080"],
    )
    assert chain["bundle_079"] == before_079
    assert chain["consistency_080"] == before_080
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyService().build(  # noqa: E501
        final_attestation=chain["final_081"]
    )
    assert chain["final_081"] == before_081
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build(  # noqa: E501
        session_id=sid,
        final_attestation=chain["final_081"],
        final_attestation_consistency=chain["consistency_082"],
    )
    assert chain["final_081"] == before_081
    assert chain["consistency_082"] == before_082
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
        package=chain["package_083"]
    )
    assert chain["package_083"] == before_083
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build(  # noqa: E501
        session_id=sid,
        final_attestation_package=chain["package_083"],
        final_attestation_package_consistency=chain["consistency_084"],
    )
    assert chain["package_083"] == before_083
    assert chain["consistency_084"] == before_084
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
        bundle=chain["bundle_085"]
    )
    assert chain["bundle_085"] == before_085
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=chain["response_087"]
    )
    assert chain["response_087"] == before_087
    assert chain["consistency_086"] == before_086


def test_repeated_operations_deterministic() -> None:
    sid_str = _seed_full("Task 090 determinism capture")
    first = _build_full_chain(sid_str)
    second = _build_full_chain(sid_str)
    assert first == second
    audit_first = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=first["response_087"]
    )
    audit_second = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=first["response_087"]
    )
    assert audit_first == audit_second


def test_no_network_leakage_083_085_087() -> None:
    for mod in (mod083, mod085, mod087):
        source = inspect.getsource(mod)
        for token in (
            "httpx",
            "requests",
            "get_db",
            "TestClient",
            "openai",
            "gemini",
            "anthropic",
            "ollama",
            "api_key",
            "urlopen",
            "socket",
        ):
            assert token not in source
