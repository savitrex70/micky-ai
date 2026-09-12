"""Template loader for clinical templates from JSON files."""

from pathlib import Path

from rop.templates.clinical_template import ClinicalTemplate, TemplateRule


def _load_template_from_file(path: Path) -> ClinicalTemplate:
    """Load a single clinical template from a JSON file."""
    import json

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    trigger_rules = tuple(
        TemplateRule(
            category=category,
            terms=tuple(terms),
        )
        for category, terms in data.get("trigger_rules", {}).items()
    )

    return ClinicalTemplate(
        name=data["name"],
        category=data.get("category", "General"),
        description=data.get("description", ""),
        priority=data.get("priority", 99),
        trigger_rules=trigger_rules,
        required_information=tuple(data.get("required_information", [])),
    )


def load_templates(directory: str | Path | None = None) -> tuple[ClinicalTemplate, ...]:
    """Load all clinical templates from the templates directory."""
    if directory is None:
        directory = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "knowledge"
            / "templates"
        )
    else:
        directory = Path(directory)

    if not directory.exists():
        return ()

    templates = []
    for path in sorted(directory.glob("*.json")):
        try:
            templates.append(_load_template_from_file(path))
        except Exception:
            continue

    return tuple(templates)
