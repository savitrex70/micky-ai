"""Tests for Task 101 release-chain audit of Tasks 055-100.

Independent end-to-end audit of the complete verified chain from
Tasks 055-082 through Tasks 083-100. Test layer only; no production
behavior is changed. Every artifact is produced by the real canonical
services; no contract logic is duplicated here.
"""

from __future__ import annotations

import copy
import inspect
import re
from collections.abc import Generator, Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from rop.database import Base, get_db
from rop.main import app
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle as mod095,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package as mod093,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation as mod097,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response as mod099,  # noqa: E501
)
from rop.services import (
    reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency as mod100,  # noqa: E501
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
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    _expected_bundle_fingerprint as _expected_095_bundle_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    _expected_package_fingerprint as _expected_093_package_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    _expected_final_fingerprint as _expected_097_final_fp,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService,  # noqa: E501
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency import (  # noqa: E501
    _ISSUE_ORDER as _ISSUE_ORDER_100,
)
from rop.services.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency import (  # noqa: E501
    REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100,  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService,  # noqa: E501
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

_RESPONSE_075_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "attestation_package",
    "attestation_package_consistency",
    "response_source",
)

_FINAL_081_FIELDS = (
    "available",
    "final_attestation_consistent",
    "session_id",
    "response_bundle",
    "response_bundle_consistency",
    "final_attestation_source",
    "final_attestation_fingerprint",
    "audited_final_attestation_fingerprint",
)

_RESPONSE_087_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_attestation_bundle",
    "final_attestation_bundle_consistency",
    "response_source",
)

_RESPONSE_099_FIELDS = (
    "available",
    "response_consistent",
    "session_id",
    "final_release_attestation",
    "final_release_attestation_consistency",
    "response_source",
)

_RESULT_100_FIELDS = (
    "available",
    "response_consistent",
    "session_consistent",
    "nested_attestation_consistent",
    "nested_attestation_consistency_consistent",
    "nested_bundle_consistent",
    "nested_bundle_consistency_consistent",
    "provenance_consistent",
    "response_relationship_consistent",
    "source_consistency",
    "metadata_consistent",
    "consistency_issues",
    "response_consistency_source",
)

_PATH_075 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation"
_PATH_077 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "response-package"
)
_PATH_079 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "audit-bundle"
)
_PATH_081 = "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/final"
_PATH_087 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/" "final-response"
)
_PATH_099 = (
    "/sessions/{sid}/reasoning-handoff/fully-audited/attestation/"
    "final-release-response"
)


def _create_session(user_input: str) -> str:
    resp = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-101-test"},
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
    package_093 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        response=response_087,
        response_consistency=result_088,
    )
    consistency_094 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=package_093
    )
    bundle_095 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=package_093,
        response_package_consistency=consistency_094,
    )
    consistency_096 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=bundle_095
    )
    final_097 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=bundle_095,
        response_bundle_consistency=consistency_096,
    )
    consistency_098 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService().build(  # noqa: E501
        final_attestation=final_097
    )
    with TestingSessionLocal() as db:
        response_099 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
    result_100 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=response_099
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
        "package_093": package_093,
        "consistency_094": consistency_094,
        "bundle_095": bundle_095,
        "consistency_096": consistency_096,
        "final_097": final_097,
        "consistency_098": consistency_098,
        "response_099": response_099,
        "result_100": result_100,
    }


def _seed_and_build() -> dict[str, Any]:
    sid_str = _seed_full("Task 101 release chain capture")
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


def test_release_chain_valid_and_100_consistent() -> None:
    chain = _seed_and_build()
    response_099 = chain["response_099"]
    result_100 = chain["result_100"]
    assert response_099["available"] is True
    assert response_099["response_consistent"] is True
    assert result_100["available"] is True
    assert result_100["response_consistent"] is True
    assert result_100["consistency_issues"] == []
    assert (
        result_100["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
    )


def test_session_identity_bound_through_every_level() -> None:
    chain = _seed_and_build()
    sid_str = chain["sid_str"]
    expected = str(UUID(sid_str))
    for key in (
        "response_075",
        "package_077",
        "bundle_079",
        "final_081",
        "package_083",
        "bundle_085",
        "response_087",
        "package_093",
        "bundle_095",
        "final_097",
        "response_099",
    ):
        collected: list[Any] = []
        _collect_session_ids(chain[key], collected)
        assert len(collected) >= 1
        for raw in collected:
            assert str(raw) == expected
    all_collected: list[Any] = []
    _collect_session_ids(chain["response_099"], all_collected)
    assert len(all_collected) >= 8
    for raw in all_collected:
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
    assert (
        chain["package_093"]["package_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_SOURCE_TASK_093  # noqa: E501
    )
    assert (
        chain["consistency_094"]["package_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_PACKAGE_CONSISTENCY_SOURCE_TASK_094  # noqa: E501
    )
    assert (
        chain["bundle_095"]["bundle_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_SOURCE_TASK_095  # noqa: E501
    )
    assert (
        chain["consistency_096"]["bundle_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_BUNDLE_CONSISTENCY_SOURCE_TASK_096  # noqa: E501
    )
    assert (
        chain["final_097"]["final_attestation_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_SOURCE_TASK_097  # noqa: E501
    )
    assert (
        chain["consistency_098"]["final_attestation_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_CONSISTENCY_SOURCE_TASK_098  # noqa: E501
    )
    assert (
        chain["response_099"]["response_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099  # noqa: E501
    )
    assert (
        chain["result_100"]["response_consistency_source"]
        == REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_100  # noqa: E501
    )


def test_every_fingerprint_is_lowercase_sha256() -> None:
    chain = _seed_and_build()
    pairs: list[tuple[str, Any]] = []
    _collect_fingerprint_pairs(chain["response_099"], pairs)
    assert len(pairs) >= 14
    for _key, value in pairs:
        assert isinstance(value, str)
        assert _FINGERPRINT_RE.fullmatch(value) is not None
    audit_pairs: list[tuple[str, Any]] = []
    _collect_fingerprint_pairs(chain["result_100"], audit_pairs)
    for _key, value in audit_pairs:
        assert isinstance(value, str)
        assert _FINGERPRINT_RE.fullmatch(value) is not None


def test_audited_fingerprints_equal_siblings() -> None:
    chain = _seed_and_build()
    envelop: list[Mapping[str, Any]] = []
    _collect_mappings(chain["response_099"], envelop)
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
    assert checked >= 14


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
    assert (
        _expected_093_package_fp(chain["package_093"])
        == chain["package_093"]["package_fingerprint"]
    )
    assert (
        _expected_093_package_fp(chain["package_093"])
        == chain["package_093"]["audited_package_fingerprint"]
    )
    assert (
        _expected_095_bundle_fp(chain["bundle_095"])
        == chain["bundle_095"]["bundle_fingerprint"]
    )
    assert (
        _expected_095_bundle_fp(chain["bundle_095"])
        == chain["bundle_095"]["audited_bundle_fingerprint"]
    )
    assert (
        _expected_097_final_fp(chain["final_097"])
        == chain["final_097"]["final_attestation_fingerprint"]
    )
    assert (
        _expected_097_final_fp(chain["final_097"])
        == chain["final_097"]["audited_final_attestation_fingerprint"]
    )


def test_later_flags_evidence_derived() -> None:
    chain = _seed_and_build()
    assert chain["package_077"]["package_consistent"] == bool(
        chain["response_075"].get("response_consistent", False)
        and chain["consistency_076"].get("response_consistent", False)
    )
    assert chain["bundle_079"]["bundle_consistent"] == bool(
        chain["package_077"].get("package_consistent", False)
        and chain["consistency_078"].get("package_consistent", False)
    )
    assert chain["final_081"]["final_attestation_consistent"] == bool(
        chain["bundle_079"].get("bundle_consistent", False)
        and chain["consistency_080"].get("bundle_consistent", False)
    )
    assert chain["package_083"]["package_consistent"] == bool(
        chain["final_081"].get("final_attestation_consistent", False)
        and chain["consistency_082"].get("final_attestation_consistent", False)
    )
    assert chain["bundle_085"]["bundle_consistent"] == bool(
        chain["package_083"].get("package_consistent", False)
        and chain["consistency_084"].get("package_consistent", False)
    )
    assert chain["response_087"]["response_consistent"] == bool(
        chain["consistency_086"].get("bundle_consistent", False)
    )
    assert chain["package_093"]["package_consistent"] == bool(
        chain["response_087"].get("response_consistent", False)
        and chain["result_088"].get("response_consistent", False)
    )
    assert chain["bundle_095"]["bundle_consistent"] == bool(
        chain["package_093"].get("package_consistent", False)
        and chain["consistency_094"].get("package_consistent", False)
    )
    assert chain["final_097"]["final_attestation_consistent"] == bool(
        chain["bundle_095"].get("bundle_consistent", False)
        and chain["consistency_096"].get("bundle_consistent", False)
    )
    assert chain["response_099"]["response_consistent"] == bool(
        chain["consistency_098"].get("final_attestation_consistent", False)
    )
    assert chain["result_100"]["response_consistent"] == (
        chain["result_100"]["consistency_issues"] == []
    )


def test_legitimate_defect_at_087_preserved_with_refreshed_prints() -> None:
    chain = _seed_and_build()
    sid = UUID(chain["sid_str"])
    valid_087 = chain["response_087"]
    bundle_085 = copy.deepcopy(valid_087["final_attestation_bundle"])
    nested_cons = bundle_085["final_attestation_package_consistency"]
    nested_cons["package_fingerprint"] = "0" * 64
    nested_cons["audited_package_fingerprint"] = "0" * 64
    recomputed_bundle_fp = _expected_085_bundle_fp(bundle_085)
    bundle_085["bundle_fingerprint"] = recomputed_bundle_fp
    bundle_085["audited_bundle_fingerprint"] = recomputed_bundle_fp
    tampered_086 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
        bundle=bundle_085
    )
    assert tampered_086["bundle_consistent"] is False
    tampered_087 = {
        "available": True,
        "response_consistent": False,
        "session_id": sid,
        "final_attestation_bundle": bundle_085,
        "final_attestation_bundle_consistency": tampered_086,
        "response_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087,  # noqa: E501
    }
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService._validate_result(  # noqa: E501
        tampered_087
    )
    tampered_088 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered_087
    )
    assert tampered_088["response_consistent"] is True
    defective_093 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        response=tampered_087,
        response_consistency=tampered_088,
    )
    assert defective_093["package_consistent"] is False
    assert (
        _expected_093_package_fp(defective_093) == defective_093["package_fingerprint"]
    )
    defective_094 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=defective_093
    )
    defective_095 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=defective_093,
        response_package_consistency=defective_094,
    )
    assert defective_095["bundle_consistent"] is False
    assert _expected_095_bundle_fp(defective_095) == defective_095["bundle_fingerprint"]
    defective_096 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=defective_095
    )
    defective_097 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=defective_095,
        response_bundle_consistency=defective_096,
    )
    assert defective_097["final_attestation_consistent"] is False
    assert (
        _expected_097_final_fp(defective_097)
        == defective_097["final_attestation_fingerprint"]
    )
    defective_098 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService().build(  # noqa: E501
        final_attestation=defective_097
    )
    defective_099 = {
        "available": True,
        "response_consistent": bool(
            defective_098.get("final_attestation_consistent", False)
        ),
        "session_id": sid,
        "final_release_attestation": defective_097,
        "final_release_attestation_consistency": defective_098,
        "response_source": REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_FINAL_RELEASE_ATTESTATION_RESPONSE_SOURCE_TASK_099,  # noqa: E501
    }
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseService._validate_result(  # noqa: E501
        defective_099
    )
    assert (
        defective_099["final_release_attestation"]["final_attestation_consistent"]
        is False
    )
    audit_100 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=defective_099
    )
    assert audit_100["available"] is True
    assert audit_100["consistency_issues"] == []
    assert defective_093["package_consistent"] is False
    assert defective_095["bundle_consistent"] is False
    assert defective_097["final_attestation_consistent"] is False


def test_stale_fingerprint_at_093_detected() -> None:
    chain = _seed_and_build()
    tampered = copy.deepcopy(chain["package_093"])
    tampered["package_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
            tampered
        )
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=tampered
    )
    assert audit["package_consistent"] is False
    assert "PACKAGE_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_stale_fingerprint_at_095_detected() -> None:
    chain = _seed_and_build()
    tampered = copy.deepcopy(chain["bundle_095"])
    tampered["bundle_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService._validate_result(  # noqa: E501
            tampered
        )
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=tampered
    )
    assert audit["bundle_consistent"] is False
    assert "BUNDLE_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_stale_fingerprint_at_097_detected() -> None:
    chain = _seed_and_build()
    tampered = copy.deepcopy(chain["final_097"])
    tampered["final_attestation_fingerprint"] = "0" * 64
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService._validate_result(  # noqa: E501
            tampered
        )
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService().build(  # noqa: E501
        final_attestation=tampered
    )
    assert audit["final_attestation_consistent"] is False
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in audit["consistency_issues"]


def test_stale_fingerprint_at_099_detected_by_100() -> None:
    chain = _seed_and_build()
    tampered = copy.deepcopy(chain["response_099"])
    tampered["final_release_attestation_consistency"] = copy.deepcopy(
        chain["response_099"]["final_release_attestation_consistency"]
    )
    tampered["final_release_attestation_consistency"][
        "final_attestation_fingerprint"
    ] = ("0" * 64)
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered
    )
    assert audit["response_consistent"] is False
    assert "FINAL_ATTESTATION_FINGERPRINT_MISMATCH" in audit["consistency_issues"]
    assert audit["provenance_consistent"] is False


def test_source_tampering_detected() -> None:
    chain = _seed_and_build()
    tampered_093 = copy.deepcopy(chain["package_093"])
    tampered_093["package_source"] = "WRONG"
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService._validate_result(  # noqa: E501
            tampered_093
        )
    audit_094 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=tampered_093
    )
    assert "PACKAGE_SOURCE_MISMATCH" in audit_094["consistency_issues"]
    tampered_099 = copy.deepcopy(chain["response_099"])
    tampered_099["response_source"] = "WRONG"
    audit_100 = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered_099
    )
    assert "RESPONSE_SOURCE_MISMATCH" in audit_100["consistency_issues"]
    assert audit_100["source_consistency"] is False
    assert audit_100["response_consistent"] is False


def test_session_tampering_detected() -> None:
    chain = _seed_and_build()
    sid = UUID(chain["sid_str"])
    with pytest.raises(
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageContractError  # noqa: E501
    ):
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build(  # noqa: E501
            session_id=uuid4(),
            response=chain["response_087"],
            response_consistency=chain["result_088"],
        )
    assert sid is not None
    tampered = copy.deepcopy(chain["response_099"])
    tampered["final_release_attestation"] = copy.deepcopy(
        chain["response_099"]["final_release_attestation"]
    )
    tampered["final_release_attestation"]["session_id"] = uuid4()
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered
    )
    assert "SESSION_ID_MISMATCH" in audit["consistency_issues"]
    assert audit["session_consistent"] is False
    assert audit["response_consistent"] is False


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
    before_088 = copy.deepcopy(chain["result_088"])
    before_093 = copy.deepcopy(chain["package_093"])
    before_094 = copy.deepcopy(chain["consistency_094"])
    before_095 = copy.deepcopy(chain["bundle_095"])
    before_096 = copy.deepcopy(chain["consistency_096"])
    before_097 = copy.deepcopy(chain["final_097"])
    before_098 = copy.deepcopy(chain["consistency_098"])
    before_099 = copy.deepcopy(chain["response_099"])
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
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageService().build(  # noqa: E501
        session_id=sid,
        response=chain["response_087"],
        response_consistency=chain["result_088"],
    )
    assert chain["response_087"] == before_087
    assert chain["result_088"] == before_088
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyService().build(  # noqa: E501
        package=chain["package_093"]
    )
    assert chain["package_093"] == before_093
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleService().build(  # noqa: E501
        session_id=sid,
        response_package=chain["package_093"],
        response_package_consistency=chain["consistency_094"],
    )
    assert chain["package_093"] == before_093
    assert chain["consistency_094"] == before_094
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyService().build(  # noqa: E501
        bundle=chain["bundle_095"]
    )
    assert chain["bundle_095"] == before_095
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationService().build(  # noqa: E501
        session_id=sid,
        response_bundle=chain["bundle_095"],
        response_bundle_consistency=chain["consistency_096"],
    )
    assert chain["bundle_095"] == before_095
    assert chain["consistency_096"] == before_096
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyService().build(  # noqa: E501
        final_attestation=chain["final_097"]
    )
    assert chain["final_097"] == before_097
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=chain["response_099"]
    )
    assert chain["response_099"] == before_099
    assert chain["consistency_098"] == before_098


def test_repeated_builds_deterministic() -> None:
    sid_str = _seed_full("Task 101 determinism capture")
    first = _build_full_chain(sid_str)
    second = _build_full_chain(sid_str)
    assert first == second
    audit_first = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=first["response_099"]
    )
    audit_second = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=first["response_099"]
    )
    assert audit_first == audit_second


def test_api_endpoints_read_only_and_additive() -> None:
    sid_str = _seed_full("Task 101 api capture")
    before = client.get("/sessions", params={"limit": 100}).json()
    for path in (_PATH_075, _PATH_077, _PATH_079, _PATH_081, _PATH_087, _PATH_099):
        resp = client.get(path.format(sid=sid_str))
        assert resp.status_code == 200
    after = client.get("/sessions", params={"limit": 100}).json()
    assert len(before) == len(after)
    body_075 = client.get(_PATH_075.format(sid=sid_str)).json()
    assert set(body_075) == set(_RESPONSE_075_FIELDS)
    body_081 = client.get(_PATH_081.format(sid=sid_str)).json()
    assert set(body_081) == set(_FINAL_081_FIELDS)
    body_087 = client.get(_PATH_087.format(sid=sid_str)).json()
    assert set(body_087) == set(_RESPONSE_087_FIELDS)
    body_099 = client.get(_PATH_099.format(sid=sid_str)).json()
    assert set(body_099) == set(_RESPONSE_099_FIELDS)


def test_100_result_fields_and_issue_order() -> None:
    chain = _seed_and_build()
    result_100 = chain["result_100"]
    assert set(result_100) == set(_RESULT_100_FIELDS)
    assert result_100["consistency_issues"] == []
    tampered = copy.deepcopy(chain["response_099"])
    tampered["session_id"] = "not-a-uuid"
    tampered["response_source"] = "WRONG"
    audit = ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyService().build(  # noqa: E501
        response=tampered
    )
    issues = audit["consistency_issues"]
    assert len(issues) == len(set(issues))
    assert issues == [i for i in _ISSUE_ORDER_100 if i in set(issues)]


def test_no_network_leakage_093_095_097_099() -> None:
    for mod in (mod093, mod095, mod097, mod099, mod100):
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
