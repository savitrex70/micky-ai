#!/usr/bin/env python3
"""Run the fixed Stage 10 intent corpus and print JSON metrics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rop.capabilities.stage10_evaluation import evaluate_intent_cases

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "stage10_evaluation_v1.json"


def main() -> int:
    with CORPUS.open(encoding="utf-8") as stream:
        corpus = json.load(stream)
    report = evaluate_intent_cases(corpus["intent_cases"])
    print(json.dumps(report, indent=2, sort_keys=True))
    if (
        report["failed_cases"]
        or report["intent_precision"] < 0.98
        or report["intent_recall"] < 0.98
        or report["false_match_count"]
        or report["missed_supported_count"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
