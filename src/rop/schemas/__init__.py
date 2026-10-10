"""Pydantic schemas."""

from rop.schemas.candidate_hypothesis import CandidateHypothesisRead
from rop.schemas.decision_candidate_assessment import (
    DecisionCandidateAssessmentRead,
    DecisionCandidateAssessmentSetRead,
    DecisionCriterionAssessmentRead,
)
from rop.schemas.decision_candidate_evaluation import (
    DecisionCandidateEvaluationRead,
    DecisionEvaluationCriterionResultRead,
)
from rop.schemas.decision_candidate_set import (
    DecisionCandidateRead,
    DecisionCandidateSetRead,
)
from rop.schemas.decision_context import DecisionContextRead
from rop.schemas.decision_evaluation_consistency import (
    DecisionEvaluationConsistencyRead,
)
from rop.schemas.decision_execution import (
    DecisionExecutionRead,
    DecisionSelectedCandidateRead,
)
from rop.schemas.decision_execution_consistency import (
    DecisionExecutionConsistencyRead,
)
from rop.schemas.decision_input_bundle import DecisionInputBundleRead
from rop.schemas.decision_input_eligibility import DecisionInputEligibilityRead
from rop.schemas.decision_policy import DecisionPolicyRead
from rop.schemas.differential_decision_readiness import (
    DifferentialDecisionReadinessRead,
)
from rop.schemas.differential_rank import DifferentialRankRead
from rop.schemas.differential_ranking_consistency import (
    DifferentialRankingConsistencyRead,
)
from rop.schemas.differential_ranking_summary import DifferentialRankingSummaryRead
from rop.schemas.entity import EntityCreate, EntityRead, EntityUpdate
from rop.schemas.evaluated_evidence import EvaluatedEvidenceRead, EvidenceGroupedRead
from rop.schemas.evidence import EvidenceCreate, EvidenceRead, EvidenceUpdate
from rop.schemas.evidence_consistency import EvidenceConsistencyRead
from rop.schemas.evidence_summary import EvidenceSummaryRead
from rop.schemas.extraction import (
    ObservationExtractionRequest,
    ObservationExtractionResponse,
)
from rop.schemas.hypothesis import HypothesisCreate, HypothesisRead, HypothesisUpdate
from rop.schemas.hypothesis_score import HypothesisScoreRead
from rop.schemas.llm_output_validation import (
    LLM_OUTPUT_VALIDATION_SOURCE_TASK_105,
)
from rop.schemas.llm_privacy_boundary import (
    LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108,
)
from rop.schemas.llm_proposal_inspection import (
    LLMProposalInspectionRead,
)
from rop.schemas.llm_proposal_normalization import (
    NormalizedCandidateAssessmentRead,
    NormalizedLLMReasoningProposalRead,
)
from rop.schemas.llm_provider_isolation import (
    LLM_PROVIDER_ISOLATION_SOURCE_TASK_107,
)
from rop.schemas.llm_reasoning import (
    LLMReasoningProposalRead,
    ReasoningCandidateAssessmentRead,
)
from rop.schemas.llm_reasoning_audit import (
    LLMReasoningAuditRead,
)
from rop.schemas.llm_request_serialization import (
    LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104,
)
from rop.schemas.missing_information import MissingInformationRead
from rop.schemas.observation import (
    ObservationCreate,
    ObservationRead,
    ObservationUpdate,
)
from rop.schemas.reasoning_context import ReasoningContextRead
from rop.schemas.reasoning_context_consistency import (
    ReasoningContextConsistencyRead,
)
from rop.schemas.reasoning_handoff import ReasoningHandoffRead
from rop.schemas.reasoning_handoff_api_audit_bundle import (
    ReasoningHandoffApiAuditBundleRead,
)
from rop.schemas.reasoning_handoff_api_audit_bundle_consistency import (
    ReasoningHandoffApiAuditBundleConsistencyRead,
)
from rop.schemas.reasoning_handoff_api_audit_package import (
    ReasoningHandoffApiAuditPackageRead,
)
from rop.schemas.reasoning_handoff_api_audit_package_consistency import (
    ReasoningHandoffApiAuditPackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_api_consistency import (
    ReasoningHandoffApiConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation import (
    ReasoningHandoffFullyAuditedApiAuditAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_attestation_response_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_final_release_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_bundle_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_package import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_attestation_response_package_consistency import (  # noqa: E501
    ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_bundle import (
    ReasoningHandoffFullyAuditedApiAuditBundleRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_bundle_consistency import (
    ReasoningHandoffFullyAuditedApiAuditBundleConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_package import (
    ReasoningHandoffFullyAuditedApiAuditPackageRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_audit_package_consistency import (
    ReasoningHandoffFullyAuditedApiAuditPackageConsistencyRead,
)
from rop.schemas.reasoning_handoff_fully_audited_api_consistency import (
    ReasoningHandoffFullyAuditedApiConsistencyRead,
)
from rop.schemas.reasoning_pipeline import (
    ReasoningPipelineRead,
    ReasoningPipelineStageRead,
)
from rop.schemas.reasoning_run import (
    ReasoningRunRead,
    ReasoningRunStageRead,
)
from rop.schemas.reasoning_run_consistency import (
    ReasoningRunConsistencyRead,
)
from rop.schemas.reasoning_run_diagnostics import ReasoningRunDiagnosticsRead
from rop.schemas.reasoning_run_execution import (
    ReasoningRunExecutionRead,
    ReasoningRunExecutionStageRead,
)
from rop.schemas.reasoning_run_execution_api_audit_bundle import (
    ReasoningRunExecutionApiAuditBundleRead,
)
from rop.schemas.reasoning_run_execution_api_audit_bundle_consistency import (
    ReasoningRunExecutionApiAuditBundleConsistencyRead,
)
from rop.schemas.reasoning_run_execution_api_audit_package import (
    ReasoningRunExecutionApiAuditPackageRead,
)
from rop.schemas.reasoning_run_execution_api_audit_package_consistency import (
    ReasoningRunExecutionApiAuditPackageConsistencyRead,
)
from rop.schemas.reasoning_run_execution_audit_package import (
    ReasoningRunExecutionAuditPackageRead,
)
from rop.schemas.reasoning_run_execution_audit_package_api_consistency import (
    ReasoningRunExecutionAuditPackageApiConsistencyRead,
)
from rop.schemas.reasoning_run_execution_bundle import (
    ReasoningRunExecutionBundleRead,
)
from rop.schemas.reasoning_run_execution_bundle_consistency import (
    ReasoningRunExecutionBundleConsistencyRead,
)
from rop.schemas.reasoning_run_execution_consistency import (
    ReasoningRunExecutionConsistencyRead,
)
from rop.schemas.reasoning_run_idempotency import (
    ReasoningRunIdempotentExecutionRead,
)
from rop.schemas.reasoning_run_idempotency_audit_request import (
    ReasoningRunIdempotencyAuditRequest,
)
from rop.schemas.reasoning_run_idempotency_consistency import (
    ReasoningRunIdempotencyConsistencyRead,
)
from rop.schemas.reasoning_run_idempotency_request import (
    ReasoningRunIdempotentExecutionRequest,
)
from rop.schemas.reasoning_run_inspection import ReasoningRunInspectionRead
from rop.schemas.reasoning_run_receipt import (
    ReasoningRunReceiptHistoryRead,
    ReasoningRunReceiptInspectionRead,
    ReasoningRunReceiptRead,
)
from rop.schemas.reasoning_run_receipt_provenance_audit import (
    ReasoningRunReceiptProvenanceAuditRead,
    ReasoningRunReceiptProvenanceFindingRead,
)
from rop.schemas.reasoning_run_replay import (
    ReasoningRunReplayRead,
)
from rop.schemas.reasoning_run_replay_consistency_audit import (
    ReasoningRunReplayConsistencyAuditRead,
    ReasoningRunReplayConsistencyFindingRead,
)
from rop.schemas.reasoning_run_replay_request import (
    ReasoningRunReplayRequest,
)
from rop.schemas.reasoning_run_stage_6_certification import (
    ReasoningRunStage6CertificationRead,
)
from rop.schemas.reasoning_run_stage_6_evidence import (
    ReasoningRunStage6EvidenceRead,
)
from rop.schemas.reasoning_run_stage_6_evidence_consistency_audit import (
    ReasoningRunStage6EvidenceConsistencyAuditRead,
)
from rop.schemas.reasoning_run_stage_6_gate import ReasoningRunStage6GateRead
from rop.schemas.reasoning_run_stage_6_gate_consistency_audit import (
    ReasoningRunStage6GateConsistencyAuditRead,
)
from rop.schemas.reasoning_run_stage_6_manifest_consistency_audit import (
    ReasoningRunStage6ManifestConsistencyAuditRead,
)
from rop.schemas.reasoning_run_stage_6_readiness import (
    ReasoningRunStage6ReadinessRead,
)
from rop.schemas.reasoning_run_stage_6_readiness_consistency_audit import (
    ReasoningRunStage6ReadinessConsistencyAuditRead,
)
from rop.schemas.reasoning_run_stage_6_release_manifest import (
    ReasoningRunStage6ReleaseManifestComponentRead,
    ReasoningRunStage6ReleaseManifestRead,
)
from rop.schemas.reasoning_run_stage_7_audit_package import (
    ReasoningRunStage7AuditPackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle import (
    ReasoningRunStage7EvidenceBundleRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166,
    ReasoningRunStage7EvidenceBundleAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_bundle_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167,
    ReasoningRunStage7EvidenceBundleAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168,
    ReasoningRunStage7EvidencePackageRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169,
    ReasoningRunStage7EvidencePackageAuditRead,
)
from rop.schemas.reasoning_run_stage_7_evidence_package_audit_consistency import (
    REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170,
    ReasoningRunStage7EvidencePackageAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_audit import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172,
    ReasoningRunStage7FinalAttestationAuditRead,
)
from rop.schemas.reasoning_run_stage_7_final_attestation_consistency import (
    REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173,
    ReasoningRunStage7FinalAttestationConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_final_evidence_attestation import (
    REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171,
    ReasoningRunStage7FinalEvidenceAttestationRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175,
    ReasoningRunStage7ReleaseReadinessAuditRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_audit_consistency import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176,
    ReasoningRunStage7ReleaseReadinessAuditConsistencyRead,
)
from rop.schemas.reasoning_run_stage_7_release_readiness_projection import (
    REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174,
    ReasoningRunStage7ReleaseReadinessProjectionRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice import (
    ReasoningRunStage7VerticalSliceRead,
)
from rop.schemas.reasoning_run_stage_7_vertical_slice_audit import (
    ReasoningRunStage7VerticalSliceAuditRead,
)
from rop.schemas.reasoning_session import (
    ReasoningSessionCreate,
    ReasoningSessionRead,
    ReasoningSessionUpdate,
)
from rop.schemas.reasoning_step import ReasoningStepCreate, ReasoningStepRead
from rop.schemas.template_match import TemplateMatchRead

__all__ = [
    "CandidateHypothesisRead",
    "DecisionCandidateAssessmentRead",
    "DecisionCandidateAssessmentSetRead",
    "DecisionCandidateEvaluationRead",
    "DecisionCandidateRead",
    "DecisionCandidateSetRead",
    "DecisionContextRead",
    "DecisionCriterionAssessmentRead",
    "DecisionExecutionConsistencyRead",
    "DecisionExecutionRead",
    "DecisionInputBundleRead",
    "DecisionPolicyRead",
    "DecisionSelectedCandidateRead",
    "DecisionEvaluationCriterionResultRead",
    "DecisionEvaluationConsistencyRead",
    "DecisionInputEligibilityRead",
    "DifferentialDecisionReadinessRead",
    "DifferentialRankRead",
    "DifferentialRankingConsistencyRead",
    "DifferentialRankingSummaryRead",
    "EntityCreate",
    "EntityRead",
    "EntityUpdate",
    "EvidenceGroupedRead",
    "EvaluatedEvidenceRead",
    "EvidenceConsistencyRead",
    "EvidenceCreate",
    "EvidenceRead",
    "EvidenceSummaryRead",
    "EvidenceUpdate",
    "HypothesisCreate",
    "HypothesisRead",
    "HypothesisScoreRead",
    "HypothesisUpdate",
    "MissingInformationRead",
    "ObservationCreate",
    "ObservationExtractionRequest",
    "ObservationExtractionResponse",
    "ObservationRead",
    "ObservationUpdate",
    "LLMReasoningProposalRead",
    "LLMReasoningAuditRead",
    "NormalizedCandidateAssessmentRead",
    "NormalizedLLMReasoningProposalRead",
    "LLMProposalInspectionRead",
    "LLM_PROVIDER_ISOLATION_SOURCE_TASK_107",
    "LLM_REQUEST_SERIALIZATION_SOURCE_TASK_104",
    "LLM_OUTPUT_VALIDATION_SOURCE_TASK_105",
    "LLM_PRIVACY_BOUNDARY_SOURCE_TASK_108",
    "ReasoningCandidateAssessmentRead",
    "ReasoningContextConsistencyRead",
    "ReasoningContextRead",
    "ReasoningHandoffApiAuditBundleConsistencyRead",
    "ReasoningHandoffApiAuditBundleRead",
    "ReasoningHandoffApiAuditPackageConsistencyRead",
    "ReasoningHandoffApiAuditPackageRead",
    "ReasoningHandoffApiConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationPackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponseBundleConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationResponsePackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalReleaseAttestationResponseConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationFinalAttestationBundleConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationPackageRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationPackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponseBundleRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponseConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponsePackageRead",
    "ReasoningHandoffFullyAuditedApiAuditAttestationResponseRead",
    "ReasoningHandoffFullyAuditedApiAuditBundleConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditBundleRead",
    "ReasoningHandoffFullyAuditedApiAuditPackageConsistencyRead",
    "ReasoningHandoffFullyAuditedApiAuditPackageRead",
    "ReasoningHandoffFullyAuditedApiConsistencyRead",
    "ReasoningHandoffRead",
    "ReasoningPipelineRead",
    "ReasoningPipelineStageRead",
    "ReasoningRunConsistencyRead",
    "ReasoningRunExecutionApiAuditBundleConsistencyRead",
    "ReasoningRunExecutionApiAuditBundleRead",
    "ReasoningRunExecutionApiAuditPackageConsistencyRead",
    "ReasoningRunExecutionApiAuditPackageRead",
    "ReasoningRunExecutionAuditPackageApiConsistencyRead",
    "ReasoningRunExecutionAuditPackageRead",
    "ReasoningRunExecutionBundleConsistencyRead",
    "ReasoningRunExecutionBundleRead",
    "ReasoningRunExecutionConsistencyRead",
    "ReasoningRunExecutionRead",
    "ReasoningRunExecutionStageRead",
    "ReasoningRunIdempotentExecutionRead",
    "ReasoningRunIdempotentExecutionRequest",
    "ReasoningRunIdempotencyAuditRequest",
    "ReasoningRunIdempotencyConsistencyRead",
    "ReasoningRunReceiptHistoryRead",
    "ReasoningRunReceiptInspectionRead",
    "ReasoningRunReceiptProvenanceAuditRead",
    "ReasoningRunReceiptProvenanceFindingRead",
    "ReasoningRunReceiptRead",
    "ReasoningRunRead",
    "ReasoningRunDiagnosticsRead",
    "ReasoningRunStage6GateRead",
    "ReasoningRunStage6GateConsistencyAuditRead",
    "ReasoningRunStage6ReadinessRead",
    "ReasoningRunStage6ReadinessConsistencyAuditRead",
    "ReasoningRunStage6EvidenceRead",
    "ReasoningRunStage6EvidenceConsistencyAuditRead",
    "ReasoningRunStage6ReleaseManifestComponentRead",
    "ReasoningRunStage6ReleaseManifestRead",
    "ReasoningRunStage6ManifestConsistencyAuditRead",
    "ReasoningRunStage6CertificationRead",
    "ReasoningRunStage7AuditPackageRead",
    "ReasoningRunStage7EvidenceBundleAuditConsistencyRead",
    "ReasoningRunStage7EvidenceBundleAuditRead",
    "ReasoningRunStage7EvidenceBundleRead",
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_CONSISTENCY_SOURCE_TASK_167",
    "REASONING_RUN_STAGE_7_EVIDENCE_BUNDLE_AUDIT_SOURCE_TASK_166",
    "ReasoningRunStage7EvidencePackageRead",
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_SOURCE_TASK_168",
    "ReasoningRunStage7EvidencePackageAuditRead",
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_SOURCE_TASK_169",
    "ReasoningRunStage7EvidencePackageAuditConsistencyRead",
    "REASONING_RUN_STAGE_7_EVIDENCE_PACKAGE_AUDIT_CONSISTENCY_SOURCE_TASK_170",
    "REASONING_RUN_STAGE_7_FINAL_EVIDENCE_ATTESTATION_SOURCE_TASK_171",
    "ReasoningRunStage7FinalEvidenceAttestationRead",
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_AUDIT_SOURCE_TASK_172",
    "ReasoningRunStage7FinalAttestationAuditRead",
    "REASONING_RUN_STAGE_7_FINAL_ATTESTATION_CONSISTENCY_SOURCE_TASK_173",
    "ReasoningRunStage7FinalAttestationConsistencyRead",
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_PROJECTION_SOURCE_TASK_174",
    "ReasoningRunStage7ReleaseReadinessProjectionRead",
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_SOURCE_TASK_175",
    "ReasoningRunStage7ReleaseReadinessAuditRead",
    "REASONING_RUN_STAGE_7_RELEASE_READINESS_AUDIT_CONSISTENCY_SOURCE_TASK_176",
    "ReasoningRunStage7ReleaseReadinessAuditConsistencyRead",
    "ReasoningRunStage7VerticalSliceAuditRead",
    "ReasoningRunStage7VerticalSliceRead",
    "ReasoningRunInspectionRead",
    "ReasoningRunReplayConsistencyAuditRead",
    "ReasoningRunReplayConsistencyFindingRead",
    "ReasoningRunReplayRead",
    "ReasoningRunReplayRequest",
    "ReasoningRunStageRead",
    "ReasoningSessionCreate",
    "ReasoningSessionRead",
    "ReasoningSessionUpdate",
    "ReasoningStepCreate",
    "ReasoningStepRead",
    "TemplateMatchRead",
]
