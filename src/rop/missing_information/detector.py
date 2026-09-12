from dataclasses import dataclass

from rop.models import Observation


@dataclass(frozen=True, slots=True)
class ClinicalProfileRequirement:
    """One required information item and its observation matching rules."""

    key: str
    label: str
    observation_types: frozenset[str] = frozenset()
    text_aliases: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ClinicalProfile:
    """A configurable clinical profile and its required information."""

    name: str
    trigger_types: frozenset[str]
    trigger_aliases: frozenset[str]
    requirements: tuple[ClinicalProfileRequirement, ...]


@dataclass(frozen=True, slots=True)
class MissingInformationItem:
    """A required item not represented by the supplied observations."""

    profile: str
    key: str
    label: str

    @property
    def template(self) -> str:
        """Compatibility name for the persisted template field."""
        return self.profile


CHEST_PAIN_PROFILE = ClinicalProfile(
    name="chest_pain",
    trigger_types=frozenset({"symptom"}),
    trigger_aliases=frozenset({"chest pain"}),
    requirements=(
        ClinicalProfileRequirement("age", "Age", frozenset({"age"})),
        ClinicalProfileRequirement("sex", "Sex", frozenset({"sex"})),
        ClinicalProfileRequirement(
            "blood_pressure",
            "Blood pressure",
            frozenset({"measurement"}),
            frozenset({"blood pressure", "bp"}),
        ),
        ClinicalProfileRequirement(
            "ecg",
            "ECG",
            frozenset({"measurement", "sign"}),
            frozenset({"ecg", "electrocardiogram"}),
        ),
        ClinicalProfileRequirement(
            "troponin",
            "Troponin",
            frozenset({"measurement"}),
            frozenset({"troponin"}),
        ),
        ClinicalProfileRequirement(
            "past_cardiac_history",
            "Past cardiac history",
            frozenset({"history", "risk_factor"}),
            frozenset({"cardiac history", "heart history"}),
        ),
    ),
)


class MissingInformationDetector:
    """Detect absent information using explicit clinical profiles."""

    def __init__(
        self,
        profiles: tuple[ClinicalProfile, ...] | None = None,
        *,
        templates: tuple["ClinicalTemplate", ...] | None = None,
    ) -> None:
        configured_profiles = profiles or templates or (CHEST_PAIN_PROFILE,)
        self.profiles = {profile.name: profile for profile in configured_profiles}
        self.templates = self.profiles

    def detect(
        self,
        observations: list[Observation],
        profile_name: str | None = None,
        *,
        template_name: str | None = None,
    ) -> list[MissingInformationItem]:
        """Return missing requirements for the selected or matching profile."""
        selected_name = profile_name or template_name
        profile = self._select_profile(observations, selected_name)
        if profile is None:
            return []

        return [
            MissingInformationItem(profile.name, requirement.key, requirement.label)
            for requirement in profile.requirements
            if not self._requirement_is_observed(requirement, observations)
        ]

    def _select_profile(
        self, observations: list[Observation], profile_name: str | None
    ) -> ClinicalProfile | None:
        if profile_name is not None:
            return self.profiles.get(profile_name)

        for profile in self.profiles.values():
            if self._profile_is_active(profile, observations):
                return profile
        return None

    @staticmethod
    def _profile_is_active(
        profile: ClinicalProfile, observations: list[Observation]
    ) -> bool:
        for observation in observations:
            observation_type = observation.type.lower().strip()
            observation_text = observation.text.lower()
            if observation_type in profile.trigger_types and any(
                alias in observation_text for alias in profile.trigger_aliases
            ):
                return True
        return False

    @staticmethod
    def _requirement_is_observed(
        requirement: ClinicalProfileRequirement, observations: list[Observation]
    ) -> bool:
        for observation in observations:
            observation_type = observation.type.lower().strip()
            observation_text = observation.text.lower()
            if observation_type in requirement.observation_types and (
                not requirement.text_aliases
                or any(alias in observation_text for alias in requirement.text_aliases)
            ):
                return True
        return False


# Compatibility names keep the Task 013 API usable while profiles become primary.
@dataclass(frozen=True, slots=True)
class ClinicalTemplate:
    name: str
    trigger_types: frozenset[str]
    trigger_aliases: frozenset[str]
    rules: tuple[ClinicalProfileRequirement, ...]

    @property
    def requirements(self) -> tuple[ClinicalProfileRequirement, ...]:
        return self.rules


MissingInformationRule = ClinicalProfileRequirement
CHEST_PAIN_TEMPLATE = ClinicalTemplate(
    name=CHEST_PAIN_PROFILE.name,
    trigger_types=CHEST_PAIN_PROFILE.trigger_types,
    trigger_aliases=CHEST_PAIN_PROFILE.trigger_aliases,
    rules=CHEST_PAIN_PROFILE.requirements,
)
