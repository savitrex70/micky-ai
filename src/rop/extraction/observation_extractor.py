import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExtractedObservation:
    """A structured observation produced without external model inference."""

    text: str
    type: str
    confidence: float
    source: str = "rule_based"


class ObservationExtractor:
    """Extract a small, deterministic set of observations from clinical text."""

    _AGE_PATTERN = re.compile(r"\b(?P<age>\d{1,3})\s*[- ]?year[- ]old\b", re.I)
    _RADIATION_PATTERN = re.compile(
        r"\bradiat(?:e|es|ed|ing)\s+to\s+(?:the\s+)?"
        r"(?P<location>[a-z][a-z -]*?)(?=\s+for\b|\s+with\b|[.,;]|$)",
        re.I,
    )
    _DURATION_PATTERN = re.compile(
        r"\bfor\s+(?P<duration>\d+(?:\.\d+)?\s+"
        r"(?:seconds?|minutes?|hours?|days?|weeks?|months?))\b",
        re.I,
    )
    _SYMPTOM_PATTERN = re.compile(
        r"\b(?:(?P<severity>severe|moderate|mild)\s+)?(?P<symptom>"
        r"chest\s+pain|shortness\s+of\s+breath|headache|"
        r"abdominal\s+pain|fever|cough|nausea|dizziness)\b",
        re.I,
    )

    _SEX_VALUES = {
        "male": "Male",
        "man": "Male",
        "female": "Female",
        "woman": "Female",
    }
    _SEVERITY_VALUES = {
        "mild": "Mild",
        "moderate": "Moderate",
        "severe": "Severe",
    }
    _SYMPTOM_VALUES = {
        "abdominal pain": "Abdominal pain",
        "chest pain": "Chest pain",
        "cough": "Cough",
        "dizziness": "Dizziness",
        "fever": "Fever",
        "headache": "Headache",
        "nausea": "Nausea",
        "shortness of breath": "Shortness of breath",
    }

    def extract(self, text: str) -> list[ExtractedObservation]:
        """Extract known observations in deterministic source-text order."""
        observations: list[ExtractedObservation] = []
        observations.extend(self._extract_age(text))
        observations.extend(self._extract_sex(text))
        observations.extend(self._extract_symptom_details(text))
        observations.extend(self._extract_radiation(text))
        observations.extend(self._extract_duration(text))
        return observations

    def _extract_age(self, text: str) -> list[ExtractedObservation]:
        match = self._AGE_PATTERN.search(text)
        if match is None:
            return []
        age = match.group("age")
        return [ExtractedObservation(f"Age = {age}", "age", 0.99)]

    def _extract_sex(self, text: str) -> list[ExtractedObservation]:
        match = re.search(r"\b(male|man|female|woman)\b", text, re.I)
        if match is None:
            return []
        sex = self._SEX_VALUES[match.group(1).lower()]
        return [ExtractedObservation(f"Sex = {sex}", "sex", 0.98)]

    def _extract_symptom_details(self, text: str) -> list[ExtractedObservation]:
        match = self._SYMPTOM_PATTERN.search(text)
        if match is None:
            return []

        symptom = self._SYMPTOM_VALUES[match.group("symptom").lower()]
        observations = [ExtractedObservation(f"Symptom = {symptom}", "symptom", 0.95)]
        severity = match.group("severity").strip().lower()
        if severity:
            normalized_severity = self._SEVERITY_VALUES[severity]
            observations.append(
                ExtractedObservation(
                    f"Severity = {normalized_severity}", "severity", 0.94
                )
            )
        return observations

    def _extract_radiation(self, text: str) -> list[ExtractedObservation]:
        match = self._RADIATION_PATTERN.search(text)
        if match is None:
            return []
        location = self._normalize_phrase(match.group("location"))
        return [ExtractedObservation(f"Radiation = {location}", "radiation", 0.92)]

    def _extract_duration(self, text: str) -> list[ExtractedObservation]:
        match = self._DURATION_PATTERN.search(text)
        if match is None:
            return []
        duration = self._normalize_phrase(match.group("duration"))
        return [ExtractedObservation(f"Duration = {duration}", "duration", 0.96)]

    @staticmethod
    def _normalize_phrase(value: str) -> str:
        normalized = " ".join(value.strip().split()).lower()
        return normalized[0].upper() + normalized[1:] if normalized else normalized
