import os

import pytest

os.environ.setdefault("ROP_APP_NAME", "Reasoning Operating Platform")
os.environ.setdefault("ROP_ENVIRONMENT", "testing")
os.environ.setdefault("ROP_LOG_LEVEL", "INFO")


@pytest.fixture
def ready_bundle_evidence():
    def build(session_id: str, request_fingerprint: str = "a" * 64):
        from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
            REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
        )
        from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
            ReasoningRunStage7EvidenceBundleSnapshot,
        )
        from rop.services.reasoning_run_stage_7_audit_package import (
            REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
        )
        from rop.services.reasoning_run_stage_7_vertical_slice import (
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
        )
        from rop.services.reasoning_run_stage_7_vertical_slice_audit import (
            REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
        )

        return ReasoningRunStage7EvidenceBundleSnapshot(
            session_id=session_id,
            slice_status="READY",
            admission_status="ADMITTED",
            diagnostics_status="HEALTHY",
            provider_name="test-provider",
            model_name="test-model",
            finding_count=0,
            findings=[],
            certification_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_SOURCE_TASK_163,
            slice_audit_status="CONSISTENT",
            audit_available=True,
            audit_consistent=True,
            published_slice_status="READY",
            expected_slice_status="READY",
            audit_finding_count=0,
            audit_findings=[],
            audit_source=REASONING_RUN_STAGE_7_VERTICAL_SLICE_AUDIT_SOURCE_TASK_164,
            request_fingerprint=request_fingerprint,
            request_audit_status="CONSISTENT",
            proposal_audit_status="CONSISTENT",
            t162_audit_source=REASONING_RUN_STAGE_7_AUDIT_PACKAGE_SOURCE_TASK_162,
            bundle_status="READY",
            bundle_finding_count=0,
            bundle_findings=[],
            bundle_source=REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_SOURCE_TASK_165,
        )

    return build


os.environ.setdefault(
    "ROP_DATABASE_URL", "postgresql+psycopg://rop:rop@localhost:5432/rop"
)
