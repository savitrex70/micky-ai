"""Stage 8 deterministic baseline evaluation (Task 206).

Model-free, offline evaluation of the deterministic composition
service over versioned synthetic case sets. No trained weights,
model runtime, network access, GPU, database session, or hosted
service is used or needed.
"""

from rop.evaluation.cases import (
    CASE_SET_VERSION,
    ContradictionRuleDecl,
    EvaluationCase,
    EvaluationCaseSet,
    RequirementDecl,
    SupportRuleDecl,
)
from rop.evaluation.harness import (
    EVALUATION_PROTOCOL_VERSION,
    REPORT_SCHEMA_VERSION,
    EvaluationHarnessError,
    EvaluationReport,
    evaluate_case_set,
    load_case_set,
    report_sha256,
)

__all__ = [
    "CASE_SET_VERSION",
    "EVALUATION_PROTOCOL_VERSION",
    "REPORT_SCHEMA_VERSION",
    "ContradictionRuleDecl",
    "EvaluationCase",
    "EvaluationCaseSet",
    "EvaluationHarnessError",
    "EvaluationReport",
    "RequirementDecl",
    "SupportRuleDecl",
    "evaluate_case_set",
    "load_case_set",
    "report_sha256",
]
