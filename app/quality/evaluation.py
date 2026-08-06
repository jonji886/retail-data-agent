"""可复用的 Golden Dataset 评测函数。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from app.agent.nlq import NLQError, NaturalLanguageQueryEngine


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    question: str
    passed: bool
    row_count: int
    errors: List[str]


def run_golden(root: Path) -> List[EvaluationResult]:
    cases = json.loads((root / "configs" / "evaluation" / "golden_questions.json").read_text(encoding="utf-8"))["cases"]
    engine = NaturalLanguageQueryEngine(root)
    results: List[EvaluationResult] = []
    for case in cases:
        errors: List[str] = []
        try:
            answer = engine.answer(case["question"])
            parsed = answer.parsed
            if parsed.metric.name != case["metric"]:
                errors.append("metric=%s" % parsed.metric.name)
            if len(answer.rows) < case["min_rows"]:
                errors.append("rows=%d" % len(answer.rows))
            if "dimension" in case and case["dimension"] not in parsed.dimensions:
                errors.append("dimension=%s" % parsed.dimensions)
            if "filter" in case and dict(parsed.filters) != case["filter"]:
                errors.append("filter=%s" % dict(parsed.filters))
            if "comparison" in case and parsed.comparison != case["comparison"]:
                errors.append("comparison=%s" % parsed.comparison)
            row_count = len(answer.rows)
        except NLQError as exc:
            errors.append(str(exc))
            row_count = 0
        results.append(EvaluationResult(case["id"], case["question"], not errors, row_count, errors))
    return results

