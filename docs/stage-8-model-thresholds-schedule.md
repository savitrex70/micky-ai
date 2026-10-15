# Stage 8 Model-Specific Threshold Schedule (PROPOSED, NOT APPROVED)

**Status:** Proposal only. Nothing in this document is approved or
effective. No held-out result has been inspected, and none may be
inspected before these targets are approved through the existing
review/protocol-versioning process (`stage-8-baseline-evaluation-protocol.md`
§6: threshold changes require a reviewed version bump **before** the
affected final evaluation is run).

This document responds to the final Stage 8 completion directive's
requirement to prepare the complete proposed threshold schedule with
rationale, evidence, and the specific approval needed. It invents no
measurement, claims no approval, and does not modify any threshold,
schema, or harness.

## Where the seven thresholds live today

All seven exist in the Task 206 harness
(`src/rop/evaluation/harness.py:479–532`) as `pending` records with
reason `pending task/data approval`. They are deliberately not part
of Task 215's accepted integrity thresholds
(`MANDATORY_EVALUATION_THRESHOLD_IDS` in
`src/rop/schemas/acceptance.py`): a pending gate blocks model
acceptance and must never be defaulted.

## Proposed definitions, proposed targets, and required approval

| Threshold | Metric definition (proposed) | Proposed target | Rationale for the target | What still requires human review |
| --- | --- | --- | --- | --- |
| `model-valid-contract-rate` | Share of model outputs admitted by the Task 213 strict boundary over the evaluated suggestion stream (valid / attempted). | 1.0 (100%) | Integrity invariant: any output that fails strict validation may not be published; Stage 8 requires all accepted outputs to validate. Rejection is fail-closed, so a sub-1.0 rate means the artifact or contract is defective, not "slightly imperfect." | Approval of the rate-1.0 precedent; definition of the evaluated population (all benchmark cases vs held-out set only). |
| `model-fabricated-refs-zero` | Count of evidence references emitted from the model path that are not resolvable to the trusted input set. | 0 | Same non-negotiable integrity rule as the baseline `unsupported-references-zero` gate. Note: the approved Task 213 advisory contract carries no evidence references by construction, so the count is structurally zero while that contract stands; the metric stays mandatory so any future contract change cannot weaken it silently. | Confirm the metric stays the required zero even under the suggestion-only advisory contract (i.e., it is not defaulted away). |
| `model-false-contradiction-rate` | Contradictory outcomes attributable to the model path / evaluated suggestion stream (a suggestion cannot create one; the metric verifies none appear). | 0 | The model may never manufacture a contradiction; only readable evidence against configured exclusive pairs may produce one (Task 202–205 semantics). | None beyond approval of the zero target. |
| `model-abstention-respect` | Share of deterministic abstain/insufficient contexts where the model suggestion is withheld or non-admissible. | 1.0 (100%) and zero violations | A model suggestion must never convert a deterministic abstention into an unauthorized partial deduction; existing semantics already forbid it contractually (Task 213). | Approval; and agreement that violations count per context, not per suggestion. |
| `model-accuracy-vs-baseline` | Correctness of the model's suggestions against the held-out expected outcomes, compared with the deterministic baseline on exactly the same held-out cases, with the comparison's uncertainty treated as evidence (predeclared sample-size expectation and per-class breakdown; ties resolved against the model). | **Strict improvement floor: the model must measurably outperform the baseline — a tie with the baseline cannot establish acceptance.** The minimum improvement margin is a number review must predeclare **before** results are inspected; none is invented here. | The architecture's approved criteria require demonstrated measurable value (§2.1 goals, §6 strategy: "reject it if it does not add measurable value", §10 risks: "Compare against deterministic baseline … approved threshold decision"), so merely matching the baseline proves the simpler deterministic path is sufficient and the model must be rejected. A real-data relative comparison cannot have a defensible numeric margin before the authorized data and task scope exist. | The exact metric instantiation (which success definition), the minimum predeclared improvement margin, how the margin interacts with measurement uncertainty (minimum sample size / evidence bar declared before inspection), and subgroup limits if justified by the data — all from real-data scope review, not from results, and all explicitly pending approval. |
| `model-repeatability-offline` | Repeat-check counts over the held-out set (`checks_attempted`, `checks_completed`, `diverged`) using the same structure as the baseline determinism gate: every case executed twice on freshly constructed, identically configured instances. | `diverged == 0`, `checks_completed == checks_attempted`, no repeat error; environment = the predeclared supported local CPU environment. | Identical definition to the already-approved baseline determinism gate, not an invented number. | The environment definition (versions/hardware) and the case population. |
| `model-resource-limits` | Latency and memory within budgets declared in the evaluation configuration before the run, measured with the existing Task 214 mechanism (declared budgets, traced-memory semantics, and its documented limitations). | "Within declared budgets" — the budget values themselves must be predeclared and review-approved per environment; none are invented here. | Budget checks already exist and are self-verifying; what is missing is the review-approved budget values for a real evaluation environment. | The concrete budget values and the environment they apply to; acceptance of the Task 214 traced-memory limitation as the measurement definition. |

## Approval needed (explicitly not granted here)

1. Review and approve/reject each proposed definition and target
   above. Note that `model-accuracy-vs-baseline` explicitly requires
   review to predeclare the minimum improvement margin and the
   uncertainty/evidence bar (both strictly before any held-out
   result is inspected) plus the real-data scope, subgroups and
   margin: none of these can be invented and approval is required
   even to begin evaluation.
2. Approve a protocol version bump recording the approved schedule
   — before any final held-out evaluation is run and before any
   held-out result is inspected.
3. Only then may evaluation proceed, and only on data authorized
   under the Task 207 governance decision documented in
   `stage-8-dataset-governance.md` ("Decision required before
   real-data work").

## Evidence in the repository for these definitions

- Threshold records: `src/rop/evaluation/harness.py:479–532`.
- Baseline integrity/protocol invariants reused by the proposals:
  `unsupported-references-zero`, `run-valid`, `determinism`
  definitions in `stage-8-baseline-evaluation-protocol.md` §5–6.
- Suggestion-contract constraints relied on:
  `src/rop/schemas/advisory.py` (no evidence references carried),
  `src/rop/inference/advisory.py` (deterministic gating, abstention
  respect).
- Budget mechanism reused: `src/rop/schemas/benchmark.py`
  (`BenchmarkConfig`, `BenchmarkReport.within_declared_budgets`).
