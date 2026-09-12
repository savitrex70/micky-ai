# Clinical Template Matching Engine

## Overview

The Template Matching Engine selects the most appropriate clinical template based on extracted observations and medical entities. It is a rule-based system that does not perform diagnosis or generate hypotheses.

## How Templates Are Loaded

Templates are loaded at application startup from JSON files located in `knowledge/templates/`.

Each template file must contain the following fields:

```json
{
  "name": "acute_coronary_syndrome",
  "category": "Cardiology",
  "description": "ACS template",
  "priority": 1,
  "trigger_rules": {
    "symptom": ["chest pain", "angina"],
    "body_location": ["left arm", "substernal"]
  },
  "required_information": ["age", "sex", "blood_pressure"]
}
```

### Field Descriptions

| Field | Description |
|-------|-------------|
| `name` | Unique template identifier (snake_case) |
| `category` | Clinical category (e.g., "Cardiology") |
| `description` | Human-readable description |
| `priority` | Integer priority (lower = higher priority) |
| `trigger_rules` | Mapping of observation/entity category to trigger terms |
| `required_information` | List of required data items for this template |

### Trigger Rules Format

Trigger rules map a lowercase category name to a list of trigger terms. A match occurs when:
- An observation's `type` (lowercased) equals the category, **and**
- The observation's `text` (lowercased) contains any of the trigger terms.

Entity matching follows the same pattern using the entity's `category` and `name` fields.

## How Scoring Works

Each template is scored against the session's observations and entities:

1. **Rule category matching**: For each trigger rule category, check if any observation or entity matches.
2. **Raw score**: `(matched_rule_categories / total_rule_categories)`.
3. **Priority factor**: `1.0 / max(template.priority, 1)`.
4. **Final score**: `raw_score * priority_factor`.

The template with the highest score is selected. If no template scores above the minimum threshold (0.01), the system falls back to the `general_assessment` template.

### Confidence

Confidence is the selected template's final score, capped at 1.0. For fallback matches, confidence is fixed at 0.1.

## How Future Templates Can Be Added

1. Create a new JSON file in `knowledge/templates/`.
2. Use a unique `name` in snake_case.
3. Define `trigger_rules` with observation/entity categories and trigger terms.
4. Set `priority` (lower values rank higher).
5. Optionally define `required_information`.

Example:

```json
{
  "name": "migraine",
  "category": "Neurology",
  "description": "Migraine assessment template",
  "priority": 2,
  "trigger_rules": {
    "symptom": ["headache", "photophobia", "nausea"],
    "body_location": ["unilateral"]
  },
  "required_information": ["age", "sex", "duration", "aura_history"]
}
```

## API Endpoint

```
POST /sessions/{session_id}/match-template
```

Returns:

| Field | Description |
|-------|-------------|
| `id` | Match record UUID |
| `session_id` | Session UUID |
| `template_name` | Selected template name |
| `confidence` | Match confidence (0.0 - 1.0) |
| `matched_observations` | List of matching observation texts |
| `matched_entities` | List of matching entity names |
| `reason` | Human-readable selection reason |
| `candidates` | All evaluated candidate templates with scores |
| `created_at` | Timestamp |

## Data Model

The `TemplateMatch` model persists results:

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID | Primary key |
| `session_id` | UUID | FK to reasoning_sessions |
| `template_name` | String(255) | Selected template name |
| `confidence` | Float | Match score (0.0 - 1.0) |
| `matched_observations` | JSON | List of matched observation texts |
| `matched_entities` | JSON | List of matched entity names |
| `reason` | Text | Selection explanation |
| `candidates` | JSON | All evaluated candidates with scores |
| `created_at` | DateTime | Creation timestamp |
