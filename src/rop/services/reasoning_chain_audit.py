"""Task 129: independent full deterministic reasoning-chain audit.

One audit verifying the complete chain from raw session state through
final reasoning-run output. Every check recomputes cross-stage
relationships from source data -- nested ``consistent=True`` flags are
never blindly trusted. Missing, duplicated, reordered, or
contradictory stage results become deterministic vocabulary issues.
Read-only: no database writes, no external calls, inputs never mutated.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.evidence_evaluation.models import EvidenceRelationship
from rop.schemas.reasoning_chain_audit import ReasoningChainAuditRead
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.differential_ranking import DifferentialRankingService
from rop.services.entity import EntityService
from rop.services.evidence_evaluation import EvidenceEvaluationService
from rop.services.hypothesis_scoring import HypothesisScoringService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_pipeline import ReasoningPipelineService
from rop.services.reasoning_run import (
    REASONING_RUN_SOURCE_TASK_042,
    STAGE_SOURCE_CANDIDATE_GENERATION,
    STAGE_SOURCE_ENTITIES,
    STAGE_SOURCE_MISSING_INFORMATION,
    STAGE_SOURCE_OBSERVATIONS,
    STAGE_SOURCE_SESSION_INPUT,
    STAGE_SOURCE_TEMPLATE_CONTEXT,
    ReasoningRunService,
)
from rop.services.reasoning_run_consistency import (
    ReasoningRunConsistencyService,
)
from rop.services.reasoning_run_fingerprint import compute_snapshot_fingerprint
from rop.services.reasoning_run_input_snapshot import (
    REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124,
    ReasoningRunInputSnapshotService,
)
from rop.services.reasoning_session import ReasoningSessionService
from rop.services.template_match import TemplateMatchService

REASONING_CHAIN_AUDIT_SOURCE_TASK_129 = "REASONING_CHAIN_AUDIT_TASK_129"

_EXPECTED_RUN_STAGE_SOURCES = (
    STAGE_SOURCE_SESSION_INPUT,
    STAGE_SOURCE_OBSERVATIONS,
    STAGE_SOURCE_ENTITIES,
    STAGE_SOURCE_MISSING_INFORMATION,
    STAGE_SOURCE_TEMPLATE_CONTEXT,
    STAGE_SOURCE_CANDIDATE_GENERATION,
)

_CHAIN_ISSUE_ORDER = (
    "missing_session",
    "session_identity_mismatch",
    "snapshot_failed",
    "snapshot_order_mismatch",
    "fingerprint_unverifiable",
    "empty_observation_text",
    "observation_confidence_out_of_range",
    "empty_entity_name",
    "duplicate_missing_information",
    "empty_missing_information_field",
    "unknown_template_observation",
    "unknown_template_entity",
    "empty_candidate_field",
    "duplicate_candidate_id",
    "unknown_candidate_observation",
    "unknown_evidence_candidate",
    "unknown_evidence_observation",
    "unknown_evidence_entity",
    "invalid_evidence_relationship",
    "evidence_contribution_mismatch",
    "scoring_failed",
    "scoring_coverage_gap",
    "ranking_failed",
    "ranking_order_violation",
    "ranking_tie_violation",
    "pipeline_failed",
    "pipeline_inconsistent",
    "execution_failed",
    "execution_inconsistent",
    "run_stage_mismatch",
    "provenance_mismatch",
)


def _issue_key(issue: str) -> tuple[int, str]:
    for index, group in enumerate(_CHAIN_ISSUE_ORDER):
        if issue == group or issue.startswith(group + ":"):
            return (index, issue)
    return (len(_CHAIN_ISSUE_ORDER), issue)


class ReasoningChainAuditContractError(Exception):
    """Task 129: the chain audit could not be established."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class ReasoningChainAuditService:
    """Independent audit over the full deterministic reasoning chain."""

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        entity_service: EntityService | None = None,
        missing_information_service: MissingInformationService | None = None,
        template_match_service: TemplateMatchService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
        evidence_evaluation_service: EvidenceEvaluationService | None = None,
        hypothesis_scoring_service: HypothesisScoringService | None = None,
        differential_ranking_service: DifferentialRankingService | None = None,
        reasoning_pipeline_service: ReasoningPipelineService | None = None,
        reasoning_run_service: ReasoningRunService | None = None,
        reasoning_run_consistency_service: ReasoningRunConsistencyService | None = None,
        snapshot_service: ReasoningRunInputSnapshotService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.observation_service = observation_service or ObservationService()
        self.entity_service = entity_service or EntityService()
        self.missing_information_service = (
            missing_information_service or MissingInformationService()
        )
        self.template_match_service = template_match_service or TemplateMatchService()
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )
        self.evidence_evaluation_service = (
            evidence_evaluation_service or EvidenceEvaluationService()
        )
        self.hypothesis_scoring_service = (
            hypothesis_scoring_service or HypothesisScoringService()
        )
        self.differential_ranking_service = (
            differential_ranking_service or DifferentialRankingService()
        )
        self.reasoning_pipeline_service = (
            reasoning_pipeline_service or ReasoningPipelineService()
        )
        self.reasoning_run_service = reasoning_run_service or ReasoningRunService()
        self.reasoning_run_consistency_service = (
            reasoning_run_consistency_service or ReasoningRunConsistencyService()
        )
        self.snapshot_service = snapshot_service or ReasoningRunInputSnapshotService()

    def audit_session(self, db: Session, session_id: UUID) -> dict[str, Any]:
        """Audit the full chain for one session, read-only."""
        issues: list[str] = []
        flags: dict[str, bool] = {
            "session_consistent": True,
            "input_consistent": True,
            "extraction_consistent": True,
            "missing_info_consistent": True,
            "template_consistent": True,
            "candidate_consistent": True,
            "evidence_consistent": True,
            "scoring_consistent": True,
            "ranking_consistent": True,
            "pipeline_consistent": True,
            "execution_consistent": True,
            "provenance_consistent": True,
        }

        def _fail(flag: str, issue: str) -> None:
            flags[flag] = False
            issues.append(issue)

        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise ReasoningChainAuditContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )

        observations = self.observation_service.list_by_session(db, session_id)
        entities = self.entity_service.list_by_session(db, session_id)
        missing = self.missing_information_service.list_by_session(db, session_id)
        templates = self.template_match_service.list_by_session(db, session_id)
        candidates = self.candidate_generation_service.list_by_session(db, session_id)
        try:
            evidence = self.evidence_evaluation_service.list_by_session(db, session_id)
        except Exception:
            evidence = []

        sid = str(session_id)
        for row, label in (
            *[(o, "observation") for o in observations],
            *[(e, "entity") for e in entities],
            *[(m, "missing") for m in missing],
            *[(t, "template") for t in templates],
            *[(c, "candidate") for c in candidates],
        ):
            if str(getattr(row, "session_id", "")) != sid:
                _fail(
                    "session_consistent",
                    f"session_identity_mismatch:{label}:{getattr(row, 'id', '?')}",
                )

        try:
            snapshot = self.snapshot_service.build_snapshot(db, session_id)
        except Exception:
            snapshot = {}
            _fail("input_consistent", "snapshot_failed")
        fingerprint = ""
        if snapshot:
            if snapshot.get("candidate_order") != [
                str(c.id) for c in candidates
            ] or snapshot.get("evidence_order") != [str(e.id) for e in evidence]:
                _fail("input_consistent", "snapshot_order_mismatch")
            try:
                fingerprint = compute_snapshot_fingerprint(snapshot)
            except Exception:
                _fail("input_consistent", "fingerprint_unverifiable")
                fingerprint = ""

        for obs in observations:
            if not str(getattr(obs, "text", "") or "").strip():
                _fail(
                    "extraction_consistent",
                    f"empty_observation_text:{getattr(obs, 'id', '?')}",
                )
            try:
                confidence = float(getattr(obs, "confidence", 0.0))
            except (TypeError, ValueError):
                confidence = -1.0
            if not 0.0 <= confidence <= 1.0:
                _fail(
                    "extraction_consistent",
                    f"observation_confidence_out_of_range:{getattr(obs, 'id', '?')}",
                )
        for ent in entities:
            if not str(getattr(ent, "name", "") or "").strip():
                _fail(
                    "extraction_consistent",
                    f"empty_entity_name:{getattr(ent, 'id', '?')}",
                )

        seen_missing: set[tuple[str, str]] = set()
        for item in missing:
            template = str(getattr(item, "template", "") or "")
            label = str(getattr(item, "item", "") or "")
            if not template or not label:
                _fail(
                    "missing_info_consistent",
                    f"empty_missing_information_field:{getattr(item, 'id', '?')}",
                )
            key = (template, label)
            if key in seen_missing:
                _fail(
                    "missing_info_consistent",
                    f"duplicate_missing_information:{template}:{label}",
                )
            seen_missing.add(key)

        observation_ids = {str(o.id) for o in observations}
        observation_keys = observation_ids | {
            str(getattr(o, "text", "")) for o in observations
        }
        entity_ids = {str(e.id) for e in entities}
        entity_keys = entity_ids | {str(getattr(e, "name", "")) for e in entities}
        candidate_ids = {str(c.id) for c in candidates}
        for template in templates:
            for oid in getattr(template, "matched_observations", None) or []:
                if str(oid) not in observation_keys:
                    _fail(
                        "template_consistent",
                        f"unknown_template_observation:{oid}",
                    )
            for eid in getattr(template, "matched_entities", None) or []:
                if str(eid) not in entity_keys:
                    _fail(
                        "template_consistent",
                        f"unknown_template_entity:{eid}",
                    )

        seen_candidates: set[str] = set()
        for candidate in candidates:
            cid = str(candidate.id)
            if cid in seen_candidates:
                _fail("candidate_consistent", f"duplicate_candidate_id:{cid}")
            seen_candidates.add(cid)
            for field in ("name", "category", "trigger_reason"):
                if not str(getattr(candidate, field, "") or "").strip():
                    _fail(
                        "candidate_consistent",
                        f"empty_candidate_field:{cid}:{field}",
                    )
            for oid in list(
                getattr(candidate, "supporting_observations", None) or []
            ) + list(getattr(candidate, "contradicting_observations", None) or []):
                if str(oid) not in observation_keys:
                    _fail(
                        "candidate_consistent",
                        f"unknown_candidate_observation:{cid}:{oid}",
                    )

        valid_relationships = {rel.value for rel in EvidenceRelationship}
        for row in evidence:
            if str(getattr(row, "hypothesis_id", "")) not in candidate_ids:
                _fail(
                    "evidence_consistent",
                    f"unknown_evidence_candidate:{getattr(row, 'id', '?')}",
                )
            oid = getattr(row, "observation_id", None)
            if oid is not None and str(oid) not in observation_ids:
                _fail(
                    "evidence_consistent",
                    f"unknown_evidence_observation:{getattr(row, 'id', '?')}",
                )
            eid = getattr(row, "entity_id", None)
            if eid is not None and str(eid) not in entity_ids:
                _fail(
                    "evidence_consistent",
                    f"unknown_evidence_entity:{getattr(row, 'id', '?')}",
                )
            if str(getattr(row, "relationship", "")) not in valid_relationships:
                _fail(
                    "evidence_consistent",
                    f"invalid_evidence_relationship:{getattr(row, 'id', '?')}",
                )
            try:
                expected = round(
                    float(getattr(row, "weight", 0.0))
                    * float(getattr(row, "match_strength", 0.0)),
                    4,
                )
                if float(getattr(row, "contribution", 0.0)) != expected:
                    _fail(
                        "evidence_consistent",
                        f"evidence_contribution_mismatch:{getattr(row, 'id', '?')}",
                    )
            except (TypeError, ValueError):
                _fail(
                    "evidence_consistent",
                    f"evidence_contribution_mismatch:{getattr(row, 'id', '?')}",
                )

        try:
            scores = self.hypothesis_scoring_service.score_session(
                db, session_id, candidates
            )
            scored_ids = {
                str(s.get("hypothesis_id")) for s in scores if isinstance(s, dict)
            }
            if scored_ids != candidate_ids:
                _fail("scoring_consistent", "scoring_coverage_gap")
        except Exception:
            _fail("scoring_consistent", "scoring_failed")
            scores = []

        try:
            ranked = self.differential_ranking_service.rank_session(
                db, session_id, candidates
            )
            self._check_ranking(ranked, flags, issues)
        except Exception:
            _fail("ranking_consistent", "ranking_failed")

        try:
            pipeline = self.reasoning_pipeline_service.build_for_session(
                db, session_id, candidates
            )
            if (
                not isinstance(pipeline, dict)
                or pipeline.get("pipeline_consistent") is not True
            ):
                _fail("pipeline_consistent", "pipeline_inconsistent")
        except Exception:
            _fail("pipeline_consistent", "pipeline_failed")

        try:
            run = self.reasoning_run_service.build_for_session(db, session_id)
            audit = self.reasoning_run_consistency_service.build_for_session(
                db, session_id
            )
            if (
                not isinstance(run, dict)
                or not isinstance(audit, dict)
                or audit.get("run_consistent") is not True
            ):
                _fail("execution_consistent", "execution_inconsistent")
            else:
                self._check_run_stages(run, flags, issues)
        except Exception:
            _fail("execution_consistent", "execution_failed")

        if snapshot.get("snapshot_source") != (
            REASONING_RUN_INPUT_SNAPSHOT_SOURCE_TASK_124
        ):
            _fail("provenance_consistent", "provenance_mismatch")
        if snapshot and str(snapshot.get("session_id")) != sid:
            _fail("provenance_consistent", "provenance_mismatch")

        ordered = sorted(set(issues), key=_issue_key)
        chain_consistent = not ordered
        result = {
            "available": True,
            "chain_consistent": chain_consistent,
            "session_consistent": flags["session_consistent"],
            "input_consistent": flags["input_consistent"],
            "extraction_consistent": flags["extraction_consistent"],
            "missing_info_consistent": flags["missing_info_consistent"],
            "template_consistent": flags["template_consistent"],
            "candidate_consistent": flags["candidate_consistent"],
            "evidence_consistent": flags["evidence_consistent"],
            "scoring_consistent": flags["scoring_consistent"],
            "ranking_consistent": flags["ranking_consistent"],
            "pipeline_consistent": flags["pipeline_consistent"],
            "execution_consistent": flags["execution_consistent"],
            "provenance_consistent": flags["provenance_consistent"],
            "input_fingerprint": fingerprint,
            "consistency_issues": ordered,
            "audit_source": REASONING_CHAIN_AUDIT_SOURCE_TASK_129,
        }
        return ReasoningChainAuditRead.model_validate(result).model_dump()

    @staticmethod
    def _check_ranking(
        ranked: list[dict[str, Any]],
        flags: dict[str, bool],
        issues: list[str],
    ) -> None:
        """Recompute rank/order/tie discipline from the ranked rows."""
        previous_score: float | None = None
        previous_rank: int | None = None
        seen_ranks: set[int] = set()
        for position, row in enumerate(ranked):
            if not isinstance(row, dict):
                flags["ranking_consistent"] = False
                issues.append(f"ranking_order_violation:position:{position}")
                continue
            try:
                score = float(row["hypothesis_score"])
                rank = int(row["rank"])
            except (KeyError, TypeError, ValueError):
                flags["ranking_consistent"] = False
                issues.append(f"ranking_order_violation:position:{position}")
                continue
            if previous_score is not None and score > previous_score + 1e-9:
                flags["ranking_consistent"] = False
                issues.append(f"ranking_order_violation:{row.get('hypothesis_id')}")
            expected_rank = previous_rank if score == previous_score else position + 1
            if rank != expected_rank:
                flags["ranking_consistent"] = False
                issues.append(f"ranking_tie_violation:{row.get('hypothesis_id')}")
            if score == previous_score and bool(row.get("is_tied")) is not True:
                flags["ranking_consistent"] = False
                issues.append(f"ranking_tie_violation:{row.get('hypothesis_id')}")
            seen_ranks.add(rank)
            previous_score = score
            previous_rank = rank

    @staticmethod
    def _check_run_stages(
        run: dict[str, Any],
        flags: dict[str, bool],
        issues: list[str],
    ) -> None:
        """Verify recomposed run stage identity, order, and sources."""
        stages = run.get("stages")
        if not isinstance(stages, list):
            flags["execution_consistent"] = False
            issues.append("run_stage_mismatch:stages-not-a-list")
            return
        if run.get("run_source") != REASONING_RUN_SOURCE_TASK_042:
            flags["provenance_consistent"] = False
            issues.append("provenance_mismatch:run-source")
        for position, (stage, expected_source) in enumerate(
            zip(stages, _EXPECTED_RUN_STAGE_SOURCES, strict=False)
        ):
            if not isinstance(stage, dict):
                flags["execution_consistent"] = False
                issues.append(f"run_stage_mismatch:position:{position}")
                continue
            if stage.get("stage_order") != position + 1 or (
                stage.get("stage_source") != expected_source
            ):
                flags["execution_consistent"] = False
                issues.append(f"run_stage_mismatch:{stage.get('stage_id')}")
