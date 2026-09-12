from pathlib import Path

from rop.templates import load_templates


def test_template_loader_reads_json_files() -> None:
    templates = load_templates()

    assert len(templates) == 5
    names = {template.name for template in templates}
    assert "general_assessment" in names
    assert "acute_coronary_syndrome" in names
    assert "stroke" in names
    assert "pulmonary_embolism" in names
    assert "diabetes_assessment" in names


def test_template_loader_returns_expected_fields() -> None:
    templates = load_templates()
    acs = next(t for t in templates if t.name == "acute_coronary_syndrome")

    assert acs.category == "Cardiology"
    assert acs.priority == 1
    assert len(acs.trigger_rules) > 0
    assert len(acs.required_information) > 0


def test_template_loader_handles_missing_directory() -> None:
    templates = load_templates("/nonexistent/path")
    assert templates == ()


def test_template_loader_custom_directory() -> None:
    custom_dir = Path(__file__).resolve().parent.parent / "knowledge" / "templates"
    templates = load_templates(custom_dir)

    assert len(templates) == 5
