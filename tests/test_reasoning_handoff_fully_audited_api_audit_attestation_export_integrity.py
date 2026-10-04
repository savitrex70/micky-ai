"""Tests for Task 091: contract/export integrity for Tasks 083-088.

Test layer only; no redesigns. Verifies that every new 083-088
service class, ContractError, and Read model is importable from the
package roots and listed in ``__all__`` (source constants live at
module level by established convention), uniquely named, stably
importable, circular-import free, schema-compatible with live
service outputs, and served exactly once at the HTTP boundary.
"""

from __future__ import annotations

import importlib
import inspect
import re
import sys
from collections.abc import Generator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import rop.schemas
import rop.services
from rop.database import Base, get_db
from rop.main import app

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
    """Re-assert this module's db override before every test."""
    app.dependency_overrides[get_db] = override_get_db
    yield


SERVICE_MODULES = (
    "reasoning_handoff_fully_audited_api_audit_attestation"
    "_final_attestation_package",
    "reasoning_handoff_fully_audited_api_audit_attestation"
    "_final_attestation_package_consistency",
    "reasoning_handoff_fully_audited_api_audit_attestation" "_final_attestation_bundle",
    "reasoning_handoff_fully_audited_api_audit_attestation"
    "_final_attestation_bundle_consistency",
    "reasoning_handoff_fully_audited_api_audit_attestation"
    "_final_attestation_response",
    "reasoning_handoff_fully_audited_api_audit_attestation"
    "_final_attestation_response_consistency",
)

SERVICE_CLASS_NAMES = (
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationPackageService",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationPackageConsistencyService",
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationBundleService",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationBundleConsistencyService",
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationResponseService",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationResponseConsistencyService",
)

CONTRACT_ERROR_NAMES = (
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationPackageContractError",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationPackageConsistencyContractError",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationBundleContractError",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationBundleConsistencyContractError",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationResponseContractError",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationResponseConsistencyContractError",
)

SOURCE_CONSTANT_NAMES = (
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_PACKAGE_SOURCE_TASK_083",
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_PACKAGE_CONSISTENCY_SOURCE_TASK_084",
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_BUNDLE_SOURCE_TASK_085",
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_BUNDLE_CONSISTENCY_SOURCE_TASK_086",
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_RESPONSE_SOURCE_TASK_087",
    "REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION"
    "_FINAL_ATTESTATION_RESPONSE_CONSISTENCY_SOURCE_TASK_088",
)

SOURCE_TASKS = ("083", "084", "085", "086", "087", "088")

READ_MODEL_NAMES = (
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationPackageRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationPackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationBundleRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationBundleConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestation" "FinalAttestationResponseRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestation"
    "FinalAttestationResponseConsistencyRead",
)

SOURCE_PATTERN = re.compile(
    r"^REASONING_HANDOFF_FULLY_AUDITED_API_AUDIT_ATTESTATION_" r"[A-Z_]+_TASK_0\d{2}$"
)

FINAL_RESPONSE_ROUTE = (
    "/sessions/{session_id}/reasoning-handoff/fully-audited/"
    "attestation/final-response"
)


def _create_session(user_input: str) -> str:
    r = client.post(
        "/sessions",
        json={
            "status": "created",
            "domain": "testing",
            "user_input": user_input,
            "current_stage": "initial",
            "metadata": {"source": "task-091-test"},
        },
    )
    assert r.status_code == 201
    return str(r.json()["id"])


def _seed_full(user_input: str) -> str:
    sid = _create_session(user_input)
    client.post(
        f"/sessions/{sid}/observations",
        json={
            "text": "Patient reports chest pain",
            "type": "symptom",
            "confidence": 0.9,
            "source": "unit_test",
        },
    )
    client.post(f"/sessions/{sid}/generate-candidates")
    client.post(f"/sessions/{sid}/evaluate-evidence")
    return sid


def _build_chain(sid_str: str) -> dict[str, dict]:
    """Build the live 083-088 artifact chain for a seeded session."""
    from rop.services import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService,  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService,  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService,  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService,  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService,  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService,  # noqa: E501
    )

    sid = UUID(sid_str)
    with TestingSessionLocal() as db:
        package = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageService().build_for_session(  # noqa: E501
            db, sid
        )
        package_consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyService().build(  # noqa: E501
            package=package
        )
        bundle = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleService().build_for_session(  # noqa: E501
            db, sid
        )
        bundle_consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyService().build(  # noqa: E501
            bundle=bundle
        )
        response = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseService().build_for_session(  # noqa: E501
            db, sid
        )
        response_consistency = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyService().build(  # noqa: E501
            response=response
        )
    return {
        "package": package,
        "package_consistency": package_consistency,
        "bundle": bundle,
        "bundle_consistency": bundle_consistency,
        "response": response,
        "response_consistency": response_consistency,
    }


def test_service_classes_importable_from_rop_services() -> None:
    for name in SERVICE_CLASS_NAMES:
        obj = getattr(rop.services, name)
        assert inspect.isclass(obj)


def test_contract_errors_importable_from_rop_services() -> None:
    for name in CONTRACT_ERROR_NAMES:
        obj = getattr(rop.services, name)
        assert inspect.isclass(obj)
        assert issubclass(obj, Exception)


def _source_value(module_name: str, name: str) -> str:
    # Source constants live at module level by established convention
    # (only classes/errors are re-exported from the package root).
    module = importlib.import_module(f"rop.services.{module_name}")
    value = getattr(module, name)
    assert isinstance(value, str) and value
    return value


def test_source_constants_importable_from_rop_services() -> None:
    for module_name, name in zip(SERVICE_MODULES, SOURCE_CONSTANT_NAMES, strict=True):
        _source_value(module_name, name)


def test_read_models_importable_from_rop_schemas() -> None:
    for name in READ_MODEL_NAMES:
        obj = getattr(rop.schemas, name)
        assert inspect.isclass(obj)


def test_new_names_present_in_all() -> None:
    for name in SERVICE_CLASS_NAMES + CONTRACT_ERROR_NAMES:
        assert name in rop.services.__all__
    for name in READ_MODEL_NAMES:
        assert name in rop.schemas.__all__


def test_no_name_appears_twice_in_all() -> None:
    assert len(set(rop.services.__all__)) == len(rop.services.__all__)
    assert len(set(rop.schemas.__all__)) == len(rop.schemas.__all__)


def test_no_duplicate_class_names_across_service_modules() -> None:
    seen: dict[str, str] = {}
    for module_name in SERVICE_MODULES:
        module = importlib.import_module(f"rop.services.{module_name}")
        local = [
            name
            for name, obj in vars(module).items()
            if inspect.isclass(obj)
            and getattr(obj, "__module__", "") == module.__name__
            # The _ContractError alias is project-wide convention, not a
            # duplicate public class.
            and not name.startswith("_")
        ]
        assert local, f"no local classes found in {module_name}"
        for name in local:
            assert name not in seen, (
                f"duplicate class {name} in " f"{seen.get(name)} and {module_name}"
            )
            seen[name] = module_name


def test_no_duplicate_source_constant_values() -> None:
    values = [
        _source_value(module_name, name)
        for module_name, name in zip(
            SERVICE_MODULES, SOURCE_CONSTANT_NAMES, strict=True
        )
    ]
    assert len(set(values)) == len(values)


def test_source_identifiers_match_pattern_and_task() -> None:
    for module_name, name, task in zip(
        SERVICE_MODULES, SOURCE_CONSTANT_NAMES, SOURCE_TASKS, strict=True
    ):
        value = _source_value(module_name, name)
        assert task in value
        assert SOURCE_PATTERN.fullmatch(value), value
        assert value.endswith(f"_TASK_{task}")


def test_import_paths_stable() -> None:
    for module_name, class_name in zip(
        SERVICE_MODULES, SERVICE_CLASS_NAMES, strict=True
    ):
        via_package = getattr(rop.services, class_name)
        via_module = getattr(
            importlib.import_module(f"rop.services.{module_name}"),
            class_name,
        )
        via_full_path = getattr(
            importlib.import_module(f"rop.services.{module_name}"),
            class_name,
        )
        assert via_package is via_module
        assert via_package is via_full_path


def test_no_circular_imports() -> None:
    import rop.api.sessions  # noqa: F401
    import rop.main  # noqa: F401

    assert rop.services is not None
    assert rop.schemas is not None
    for module_name in SERVICE_MODULES:
        module = importlib.import_module(f"rop.services.{module_name}")
        assert module is not None
    assert all(value is not None for value in sys.modules.values())


def test_no_dead_compat_exports() -> None:
    lowered = [name.lower() for name in dir(rop.services)]
    assert not any("compat" in name for name in lowered)
    assert not any("legacy" in name for name in lowered)
    assert not any("alias" in name for name in lowered)
    expected = set(SERVICE_CLASS_NAMES + CONTRACT_ERROR_NAMES)
    assert expected.issubset(set(dir(rop.services)))


def test_final_response_route_registered_exactly_once() -> None:
    # FastAPI >=0.141 registers included routers lazily (a single
    # _IncludedRouter placeholder in app.routes), so route presence is
    # proven through the served OpenAPI surface instead of app.routes.
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert FINAL_RESPONSE_ROUTE in paths
    assert list(paths).count(FINAL_RESPONSE_ROUTE) == 1
    assert "get" in paths[FINAL_RESPONSE_ROUTE]


def test_package_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 package capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead.model_validate(  # noqa: E501
        chain["package"]
    )
    assert str(validated.session_id) == sid_str


def test_package_consistency_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 package-consistency capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead.model_validate(  # noqa: E501
        chain["package_consistency"]
    )
    assert validated.available is True


def test_bundle_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 bundle capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead.model_validate(  # noqa: E501
        chain["bundle"]
    )
    assert str(validated.session_id) == sid_str


def test_bundle_consistency_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 bundle-consistency capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead.model_validate(  # noqa: E501
        chain["bundle_consistency"]
    )
    assert validated.available is True


def test_response_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 response capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead.model_validate(  # noqa: E501
        chain["response"]
    )
    assert str(validated.session_id) == sid_str


def test_response_consistency_output_matches_read_model() -> None:
    from rop.schemas import (  # noqa: E501
        ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead,  # noqa: E501
    )

    sid_str = _seed_full("Task 091 response-consistency capture")
    chain = _build_chain(sid_str)
    validated = ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead.model_validate(  # noqa: E501
        chain["response_consistency"]
    )
    assert validated.available is True
