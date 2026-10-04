"""Task 131: deterministic missing-information lifecycle.

Completes the lifecycle of missing-information state on top of the
existing rule-based detector and replace-semantics repository -- no
model changes, no migrations, no AI. Every evaluation classifies each
item deterministically:

- ``NEW`` -- detected now, never recorded;
- ``PERSISTING`` -- detected now and already recorded;
- ``RESOLVED`` -- recorded under the active profile but its requirement
  is now satisfied by current observations;
- ``STALE`` -- recorded under an inactive or unknown profile, kept for
  provenance rather than silently erased.

``reconcile`` persists the current detection through the established
replace path while reporting resolved items with their deterministic
reason and satisfying observations. Candidate context is attached
read-only wherever candidates reference the item key. All matching
reuses the detector's own type/alias rule.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from rop.missing_information import MissingInformationDetector
from rop.schemas.missing_information_lifecycle import (
    MissingInformationLifecycleRead,
)
from rop.services.candidate_generation import CandidateGenerationService
from rop.services.missing_information import MissingInformationService
from rop.services.observation import ObservationService
from rop.services.reasoning_session import ReasoningSessionService

MISSING_INFORMATION_LIFECYCLE_SOURCE_TASK_131 = "MISSING_INFORMATION_LIFECYCLE_TASK_131"


class MissingInformationLifecycleContractError(Exception):
    """Task 131: the lifecycle could not be evaluated."""

    def __init__(self, invariant: str, detail: str) -> None:
        self.invariant = invariant
        super().__init__(f"[{invariant}] {detail}")


class MissingInformationLifecycleService:
    """Evaluates and reconciles missing-information lifecycle state."""

    def __init__(
        self,
        reasoning_session_service: ReasoningSessionService | None = None,
        observation_service: ObservationService | None = None,
        missing_information_service: MissingInformationService | None = None,
        candidate_generation_service: CandidateGenerationService | None = None,
    ) -> None:
        self.reasoning_session_service = (
            reasoning_session_service or ReasoningSessionService()
        )
        self.observation_service = observation_service or ObservationService()
        self.missing_information_service = (
            missing_information_service or MissingInformationService()
        )
        self.candidate_generation_service = (
            candidate_generation_service or CandidateGenerationService()
        )

    @property
    def _detector(self) -> MissingInformationDetector:
        return self.missing_information_service.detector

    def evaluate(
        self,
        db: Session,
        session_id: UUID,
        observations: list[Any] | None = None,
        profile_name: str | None = None,
    ) -> dict[str, Any]:
        """Classify lifecycle state read-only (no writes)."""
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise MissingInformationLifecycleContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        owned_observations = (
            observations
            if observations is not None
            else self.observation_service.list_by_session(db, session_id)
        )
        stored = self.missing_information_service.list_by_session(db, session_id)
        detected = self._detector.detect(owned_observations, profile_name)
        active_profile = self._active_profile_name(owned_observations, profile_name)
        candidates = self.candidate_generation_service.list_by_session(db, session_id)
        return self._build_record(
            session_id=session_id,
            profile=active_profile,
            detected=detected,
            stored=stored,
            observations=owned_observations,
            candidates=candidates,
            persisted=True,
        )

    def reconcile(
        self,
        db: Session,
        session_id: UUID,
        observations: list[Any],
        profile_name: str | None = None,
    ) -> dict[str, Any]:
        """Persist current detection, reporting lifecycle transitions."""
        session = self.reasoning_session_service.get(db, session_id)
        if session is None:
            raise MissingInformationLifecycleContractError(
                "SESSION_NOT_FOUND", "session does not exist"
            )
        before = self.evaluate(db, session_id, observations, profile_name)
        self.missing_information_service.detect_and_store(
            db, session_id, observations, profile_name
        )
        # The pre-persist evaluation already expresses this reconcile's
        # transitions (NEW created, RESOLVED leaving the store, STALE
        # untouched for provenance). Re-validate the shape as the
        # lifecycle record.
        return MissingInformationLifecycleRead.model_validate(before).model_dump()

    def check_consistency(
        self,
        db: Session,
        session_id: UUID,
        observations: list[Any] | None = None,
    ) -> list[str]:
        """Cross-check observations, records, rules, and candidates."""
        record = self.evaluate(db, session_id, observations)
        return list(record["consistency_issues"])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _active_profile_name(
        self, observations: list[Any], profile_name: str | None
    ) -> str | None:
        if profile_name is not None:
            return profile_name
        detector = self._detector
        for profile in detector.profiles.values():
            if detector._profile_is_active(profile, observations):
                return profile.name
        return None

    def _satisfying_observation_ids(
        self, template: str, key: str, observations: list[Any]
    ) -> list[str]:
        detector = self._detector
        profile = detector.profiles.get(template)
        if profile is None:
            return []
        requirement = next((r for r in profile.requirements if r.key == key), None)
        if requirement is None:
            return []
        matched: list[str] = []
        for observation in observations:
            try:
                obs_type = str(observation.type).lower().strip()
                obs_text = str(observation.text).lower()
            except Exception:
                continue
            if obs_type in requirement.observation_types and (
                not requirement.text_aliases
                or any(alias in obs_text for alias in requirement.text_aliases)
            ):
                matched.append(str(observation.id))
        return sorted(matched)

    def _candidate_ids_for_key(
        self, key: str, label: str, candidates: list[Any]
    ) -> list[str]:
        matched: list[str] = []
        for candidate in candidates:
            entries = list(getattr(candidate, "missing_information", None) or [])
            if key in entries or label in entries:
                matched.append(str(candidate.id))
        return sorted(matched)

    def _build_record(
        self,
        *,
        session_id: UUID,
        profile: str | None,
        detected: list[Any],
        stored: list[Any],
        observations: list[Any],
        candidates: list[Any],
        persisted: bool,
    ) -> dict[str, Any]:
        issues: list[str] = []
        detector = self._detector
        # The established store persists requirement LABELS while
        # detection speaks in KEYs, so both sides are normalized to
        # (template, label) for comparison, resolving labels back to
        # keys through the active profile's requirements.
        label_to_key: dict[tuple[str, str], str] = {}
        for profile_def in detector.profiles.values():
            for requirement in profile_def.requirements:
                label_to_key[(profile_def.name, requirement.label)] = requirement.key
        detected_labels = {(item.template, item.label) for item in detected}
        stored_labels = {(row.template, row.item) for row in stored}

        for row in stored:
            if row.template not in detector.profiles:
                issues.append(f"unknown_profile_template:{row.template}")
            else:
                keys = {r.key for r in detector.profiles[row.template].requirements}
                if row.item not in keys and row.item not in {
                    r.label for r in detector.profiles[row.template].requirements
                }:
                    issues.append(f"unknown_requirement_key:{row.template}:{row.item}")
        # Detection must be deterministic: run twice, same result.
        repeat = {
            (item.template, item.label)
            for item in detector.detect(
                observations,
                profile if profile in detector.profiles else None,
            )
        }
        if repeat != detected_labels:
            issues.append("detection_nondeterministic")

        items: list[dict[str, Any]] = []
        for item in detected:
            label_key = (item.template, item.label)
            state = "PERSISTING" if label_key in stored_labels else "NEW"
            reason = (
                "still required by current observations"
                if state == "PERSISTING"
                else "newly required by current observations"
            )
            items.append(
                {
                    "template": item.template,
                    "key": item.key,
                    "label": item.label,
                    "state": state,
                    "reason": reason,
                    "satisfying_observation_ids": [],
                    "candidate_ids": self._candidate_ids_for_key(
                        item.key, item.label, candidates
                    ),
                }
            )
        for row in stored:
            label_key = (row.template, row.item)
            if label_key in detected_labels:
                continue
            requirement_key = label_to_key.get(label_key, row.item)
            satisfying = self._satisfying_observation_ids(
                row.template, requirement_key, observations
            )
            if satisfying and (profile is None or row.template == profile):
                items.append(
                    {
                        "template": row.template,
                        "key": requirement_key,
                        "label": row.item,
                        "state": "RESOLVED",
                        "reason": ("requirement satisfied by current observations"),
                        "satisfying_observation_ids": satisfying,
                        "candidate_ids": self._candidate_ids_for_key(
                            requirement_key, row.item, candidates
                        ),
                    }
                )
            else:
                items.append(
                    {
                        "template": row.template,
                        "key": requirement_key,
                        "label": row.item,
                        "state": "STALE",
                        "reason": (
                            "recorded under an inactive or unknown profile; "
                            "kept for provenance"
                        ),
                        "satisfying_observation_ids": [],
                        "candidate_ids": self._candidate_ids_for_key(
                            requirement_key, row.item, candidates
                        ),
                    }
                )
        items.sort(key=lambda e: (e["template"], e["key"], e["state"]))
        record = {
            "available": True,
            "lifecycle_consistent": not issues,
            "session_id": str(session_id),
            "profile": profile,
            "items": items,
            "consistency_issues": sorted(set(issues)),
            "lifecycle_source": MISSING_INFORMATION_LIFECYCLE_SOURCE_TASK_131,
        }
        return MissingInformationLifecycleRead.model_validate(record).model_dump()
