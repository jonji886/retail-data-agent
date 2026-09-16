"""共享的 LLM Golden 评测判定逻辑。"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def check_case(state: Dict[str, Any], case: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """按 Agent 用例的预期行为判定通过与否。"""
    errors: List[str] = []
    intent = state.get("intent")
    if case.get("should_reject"):
        if intent != "unsupported":
            errors.append("should_reject but intent=%s" % intent)
        if state.get("tool_calls"):
            errors.append("expected no tool execution but got tool_calls")
        return not errors, errors
    if case.get("should_deny"):
        if state.get("permission_decision") != "deny":
            errors.append("should_deny but permission=%s" % state.get("permission_decision"))
        if state.get("tool_calls"):
            errors.append("expected no tool execution but got tool_calls")
        return not errors, errors
    if case.get("should_allow"):
        if state.get("permission_decision") != "allow":
            errors.append("should_allow but permission=%s" % state.get("permission_decision"))
        result = state.get("result") or {}
        if not result.get("success"):
            errors.append("allowed query execution failed: %s" % result.get("error_message"))
        plan = state.get("query_plan", {})
        for key, value in case.get("expected_filter", {}).items():
            if plan.get("filters", {}).get(key) != value:
                errors.append("expected_filter %s=%s but got %s" % (
                    key, value, plan.get("filters", {}).get(key),
                ))
        return not errors, errors

    expected = case.get("intent")
    if case.get("baseline_only"):
        if intent not in ("metric_query", "trend_analysis"):
            errors.append("intent=%s expected metric_query/trend_analysis" % intent)
    elif expected == "trend_analysis":
        if intent not in ("metric_query", "trend_analysis"):
            errors.append("intent=%s expected metric_query/trend_analysis" % intent)
    elif expected and intent != expected:
        errors.append("intent=%s expected=%s" % (intent, expected))

    if state.get("error_type"):
        errors.append("error_type=%s: %s" % (state.get("error_type"), state.get("error_message")))
    result = state.get("result") or {}
    if expected in ("attribution_analysis", "anomaly_analysis", "report_generation"):
        if not result.get("success"):
            errors.append("skill failed: %s" % result.get("error_message"))
    elif not result.get("success"):
        errors.append("query execution failed: %s" % result.get("error_message"))
    return not errors, errors


def check_ground_truth(state: Dict[str, Any], case: Dict[str, Any]) -> Tuple[bool, str]:
    """检查 Golden 用例可选的 ground truth 行数与聚合值。"""
    ground_truth = case.get("ground_truth")
    if not ground_truth:
        return True, ""
    rows = (state.get("result") or {}).get("rows") or []
    tolerance = ground_truth.get("tolerance", 0.01)
    expected_rows = ground_truth.get("row_count")
    if expected_rows is not None and len(rows) != expected_rows:
        return False, "row_count=%d expected=%d" % (len(rows), expected_rows)
    expected_value = ground_truth.get("value")
    if expected_value is not None:
        actual = sum(float(row.get("value") or row.get("current_value") or 0) for row in rows)
        if abs(actual - expected_value) > tolerance:
            return False, "value=%.2f expected=%.2f" % (actual, expected_value)
    return True, ""
