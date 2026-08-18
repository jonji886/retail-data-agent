"""validate_result 节点：验证 Skill 返回结果的结构与数值合法性。

失败后不让 LLM 编造答案，直接走 error path。
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List

from app.agent.contracts import ErrorType
from app.agent.state import AgentState


def validate_result(state: AgentState) -> AgentState:
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    result = state.get("result")
    events = list(state.get("trace_events", []))

    errors: List[str] = []

    if result is None:
        errors.append("result 为空")
    elif not isinstance(result, dict):
        errors.append("result 结构非法")
    elif not result.get("success"):
        # Skill 本身已标记失败，直接透传
        events.append({
            "trace_id": trace_id, "node": "validate_result",
            "start_at": started, "end_at": time.monotonic(),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "status": "error", "reason": "skill_failed",
        })
        return {
            **state,
            "error_type": result.get("error_type", ErrorType.RESULT_VALIDATION_ERROR),
            "error_message": result.get("error_message", "Skill 返回失败"),
            "trace_events": events,
        }
    else:
        # 检查数值合法性
        _check_numeric_values(result, errors)
        # 检查空结果
        if "rows" in result and result["rows"] is not None:
            if not result["rows"]:
                # 空结果不是错误，但标记 EMPTY_RESULT
                events.append({
                    "trace_id": trace_id, "node": "validate_result",
                    "status": "success", "warning": "empty_result",
                })
            else:
                events.append({
                    "trace_id": trace_id, "node": "validate_result",
                    "start_at": started, "end_at": time.monotonic(),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "status": "success",
                })
        else:
            events.append({
                "trace_id": trace_id, "node": "validate_result",
                "start_at": started, "end_at": time.monotonic(),
                "latency_ms": int((time.monotonic() - started) * 1000),
                "status": "success",
            })

    if errors:
        events.append({
            "trace_id": trace_id, "node": "validate_result",
            "status": "error", "errors": errors,
        })
        return {
            **state,
            "error_type": ErrorType.RESULT_VALIDATION_ERROR,
            "error_message": "; ".join(errors),
            "trace_events": events,
        }
    return {**state, "trace_events": events}


def _check_numeric_values(result: Dict[str, Any], errors: List[str]) -> None:
    """检查 rows 中的数值是否为 NaN/Infinity。"""
    rows = result.get("rows")
    if not isinstance(rows, list):
        return
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    errors.append("row[%d].%s 为 NaN/Infinity" % (i, key))
