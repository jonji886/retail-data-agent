"""Evaluation 2.0：支持 intent / plan / result / permission / security 多维评测。

输出指标：Plan Accuracy、Execution Success Rate、Result Accuracy、
Unsupported Reject Rate、Permission Safety Pass Rate、Overall Pass Rate。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.graph import run_agent
from app.agent.nlq import NLQError, NaturalLanguageQueryEngine


@dataclass(frozen=True)
class EvaluationResult:
    case_id: str
    question: str
    category: str
    passed: bool
    intent_match: bool
    execution_success: bool
    result_accuracy: Optional[bool]
    permission_pass: Optional[bool]
    row_count: int
    errors: List[str] = field(default_factory=list)
    latency_ms: int = 0
    should_reject: bool = False


def _load_cases(root: Path) -> List[Dict[str, Any]]:
    raw = json.loads((root / "configs" / "evaluation" / "golden_questions.json").read_text(encoding="utf-8"))
    return raw.get("cases", raw if isinstance(raw, list) else [])


def _run_baseline(root: Path, case: Dict[str, Any]) -> EvaluationResult:
    """确定性 baseline 评测（仅 metric_query 类用 NLQ 引擎，其它走 Agent）。"""
    case_id = case["id"]
    question = case["question"]
    category = case.get("category", "normal")
    errors: List[str] = []

    # 对于 unsupported / security / permission 类，必须走 Agent 图
    if case.get("should_reject") or case.get("should_deny") or case.get("should_allow") or \
       case.get("intent") in ("attribution_analysis", "anomaly_analysis", "report_generation", "unsupported"):
        return _run_agent_case(root, case)

    # metric_query / trend 用确定性引擎快速评测
    engine = NaturalLanguageQueryEngine(root)
    intent_match = True
    execution_success = False
    result_accuracy: Optional[bool] = None
    row_count = 0
    # baseline_only 用例：用确定性引擎测试 metric/dimension/filter，不校验 intent（Agent 会识别为 trend_analysis）
    check_intent = not case.get("baseline_only", False)
    try:
        answer = engine.answer(question)
        parsed = answer.parsed
        if check_intent and case.get("intent") and case["intent"] not in ("metric_query", "trend_analysis"):
            if parsed.metric.name != case.get("metric"):
                errors.append("metric=%s expected=%s" % (parsed.metric.name, case.get("metric")))
                intent_match = False
        if "metric" in case and parsed.metric.name != case["metric"]:
            errors.append("metric=%s expected=%s" % (parsed.metric.name, case["metric"]))
            intent_match = False
        if "dimension" in case and case["dimension"] not in parsed.dimensions:
            errors.append("dimension=%s" % parsed.dimensions)
        if "filter" in case and dict(parsed.filters) != case["filter"]:
            errors.append("filter=%s expected=%s" % (dict(parsed.filters), case["filter"]))
        if "comparison" in case and parsed.comparison != case["comparison"]:
            errors.append("comparison=%s" % parsed.comparison)
        row_count = len(answer.rows)
        if row_count < case.get("min_rows", 1):
            errors.append("rows=%d min=%d" % (row_count, case.get("min_rows", 1)))
        execution_success = row_count > 0 or case.get("expect_empty", False)
        # ground truth result 检查：行数 + 整体聚合值（单行取该行，多行取各行求和）
        if "ground_truth" in case:
            gt = case["ground_truth"]
            tolerance = gt.get("tolerance", 0.01)
            expected_value = gt.get("value")
            expected_rows = gt.get("row_count")
            ok = True
            if expected_rows is not None and row_count != expected_rows:
                ok = False
                errors.append("ground_truth rows=%d expected=%d" % (row_count, expected_rows))
            if ok and expected_value is not None:
                actual = sum(
                    float(r.get("value") or r.get("current_value") or 0)
                    for r in answer.rows
                ) if answer.rows else 0.0
                if abs(actual - expected_value) > tolerance:
                    ok = False
                    errors.append("ground_truth: %.2f != %.2f" % (actual, expected_value))
            result_accuracy = ok
    except NLQError as exc:
        errors.append(str(exc))
        intent_match = False

    passed = not errors and (result_accuracy is not False)
    return EvaluationResult(
        case_id=case_id, question=question, category=category,
        passed=passed, intent_match=intent_match,
        execution_success=execution_success, result_accuracy=result_accuracy,
        permission_pass=None, row_count=row_count, errors=errors,
    )


def _run_agent_case(root: Path, case: Dict[str, Any]) -> EvaluationResult:
    """通过完整 Agent 图评测（permission / security / attribution / anomaly / report）。"""
    import time
    case_id = case["id"]
    question = case["question"]
    category = case.get("category", "normal")
    errors: List[str] = []
    start = time.monotonic()

    user_id = case.get("user_id", "user_hq")
    role = case.get("role", "hq_manager")
    data_scope = case.get("data_scope", {"scope": "all"})

    state = run_agent(question, root, user_id=user_id, role=role, data_scope=data_scope)
    latency_ms = int((time.monotonic() - start) * 1000)

    intent_match = state.get("intent") == case.get("intent")
    if not intent_match:
        errors.append("intent=%s expected=%s" % (state.get("intent"), case.get("intent")))

    # should_reject: 必须 unsupported
    if case.get("should_reject"):
        if state.get("intent") != "unsupported":
            errors.append("should_reject but intent=%s" % state.get("intent"))
    # should_deny: 必须权限拒绝
    if case.get("should_deny"):
        if state.get("permission_decision") != "deny":
            errors.append("should_deny but permission=%s" % state.get("permission_decision"))
    # should_allow: 必须权限通过
    if case.get("should_allow"):
        if state.get("permission_decision") != "allow":
            errors.append("should_allow but permission=%s" % state.get("permission_decision"))

    # expected_filter 检查
    if "expected_filter" in case:
        plan = state.get("query_plan", {})
        actual_filters = plan.get("filters", {})
        for k, v in case["expected_filter"].items():
            if actual_filters.get(k) != v:
                errors.append("expected_filter %s=%s but got %s" % (k, v, actual_filters.get(k)))

    # 归因/异常/报告：检查执行成功
    execution_success = False
    if case.get("intent") in ("attribution_analysis", "anomaly_analysis", "report_generation"):
        result = state.get("result") or {}
        execution_success = bool(result.get("success"))
        if not execution_success:
            errors.append("skill failed: %s" % result.get("error_message"))

    permission_pass: Optional[bool] = None
    if case.get("should_deny") or case.get("should_allow"):
        if case.get("should_deny"):
            permission_pass = state.get("permission_decision") == "deny"
        else:
            permission_pass = state.get("permission_decision") == "allow"

    passed = not errors
    return EvaluationResult(
        case_id=case_id, question=question, category=category,
        passed=passed, intent_match=intent_match,
        execution_success=execution_success, result_accuracy=None,
        permission_pass=permission_pass, row_count=0, errors=errors,
        latency_ms=latency_ms, should_reject=bool(case.get("should_reject")),
    )


def run_golden(root: Path) -> List[EvaluationResult]:
    """运行完整 Golden 评测（兼容旧接口）。"""
    cases = _load_cases(root)
    results: List[EvaluationResult] = []
    for case in cases:
        results.append(_run_baseline(root, case))
    return results


def run_golden_v2(root: Path) -> Dict[str, Any]:
    """Evaluation 2.0：返回结构化评测报告。"""
    cases = _load_cases(root)
    results: List[EvaluationResult] = []
    for case in cases:
        results.append(_run_baseline(root, case))

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    plan_correct = sum(1 for r in results if r.intent_match)
    exec_success = sum(1 for r in results if r.execution_success)
    result_correct = sum(1 for r in results if r.result_accuracy is True)
    result_checked = sum(1 for r in results if r.result_accuracy is not None)
    unsupported_cases = [r for r in results if r.should_reject]
    unsupported_rejected = sum(1 for r in unsupported_cases if r.passed)
    perm_cases = [r for r in results if r.category == "permission"]
    perm_passed = sum(1 for r in perm_cases if r.permission_pass is True)

    return {
        "total": total,
        "passed": passed,
        "overall_pass_rate": passed / total if total else 0,
        "plan_accuracy": plan_correct / total if total else 0,
        "execution_success_rate": exec_success / total if total else 0,
        "result_accuracy": result_correct / result_checked if result_checked else None,
        "unsupported_reject_rate": unsupported_rejected / len(unsupported_cases) if unsupported_cases else None,
        "permission_safety_pass_rate": perm_passed / len(perm_cases) if perm_cases else None,
        "results": [
            {
                "case_id": r.case_id, "question": r.question, "category": r.category,
                "passed": r.passed, "intent_match": r.intent_match,
                "execution_success": r.execution_success,
                "result_accuracy": r.result_accuracy,
                "permission_pass": r.permission_pass,
                "row_count": r.row_count, "errors": r.errors,
                "latency_ms": r.latency_ms,
            }
            for r in results
        ],
    }
