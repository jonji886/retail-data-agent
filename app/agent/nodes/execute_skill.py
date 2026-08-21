"""execute_skill 节点：根据 intent 从 Skill Registry 获取并执行对应 Skill。

不写大型 if/elif 散落代码，统一通过 SKILL_REGISTRY 调度。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from app.agent.contracts import ErrorType, QueryPlan
from app.agent.state import AgentState
from app.skills.registry import get_skill


def execute_skill(state: AgentState) -> AgentState:
    root = Path(state.get("_root", "."))  # type: ignore[arg-type]
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    intent = state.get("intent", "")
    plan_dict = state.get("query_plan", {})

    events = list(state.get("trace_events", []))
    tool_calls = list(state.get("tool_calls", []))
    tool_results = list(state.get("tool_results", []))

    if not intent:
        return {
            **state, "error_type": ErrorType.INTERNAL_ERROR,
            "error_message": "缺少 intent", "trace_events": events,
        }

    try:
        plan = _plan_from_dict(plan_dict, intent)
        skill = get_skill(intent)
        authorized_filters = plan_dict.get("filters", {})
        context: Dict[str, Any] = {
            "root": root,
            "authorized_filters": dict(authorized_filters),
            "user_id": state.get("user_id", "user_hq"),
            "role": state.get("role", "hq_manager"),
            "data_source": state.get("_data_source"),
        }
        result = skill(plan, context)
    except KeyError as exc:
        events.append({
            "trace_id": trace_id, "node": "execute_skill",
            "status": "error", "error": str(exc),
        })
        return {
            **state, "error_type": ErrorType.UNSUPPORTED_INTENT,
            "error_message": str(exc), "trace_events": events,
        }
    except Exception as exc:  # noqa: BLE001
        events.append({
            "trace_id": trace_id, "node": "execute_skill",
            "status": "error", "error": str(exc),
        })
        return {
            **state, "error_type": ErrorType.INTERNAL_ERROR,
            "error_message": "Skill 执行失败：%s" % exc, "trace_events": events,
        }

    # 收集 tool 调用记录
    for tr in result.get("tool_results", []):
        tool_calls.append({
            "tool": tr.get("metadata", {}).get("tool", intent),
            "status": "success" if tr.get("success") else "error",
        })
        tool_results.append(tr)

    events.append({
        "trace_id": trace_id, "node": "execute_skill",
        "start_at": started, "end_at": time.monotonic(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status": "success" if result.get("success") else "error",
        "skill": intent,
    })

    if not result.get("success"):
        return {
            **state,
            "error_type": result.get("error_type", ErrorType.INTERNAL_ERROR),
            "error_message": result.get("error_message", "Skill 执行失败"),
            "tool_calls": tool_calls, "tool_results": tool_results,
            "trace_events": events,
        }
    return {
        **state, "result": result, "current_skill": intent,
        "tool_calls": tool_calls, "tool_results": tool_results,
        "trace_events": events,
    }


def _plan_from_dict(d: Dict[str, Any], intent: str) -> QueryPlan:
    """从 dict 重建 QueryPlan。"""
    from datetime import date
    start = d.get("start_date")
    end = d.get("end_date")
    return QueryPlan(
        intent=intent,
        metric=d.get("metric", "sales_amount"),
        dimensions=list(d.get("dimensions", [])),
        filters=dict(d.get("filters", {})),
        time_grain=d.get("time_grain", "month"),
        start_date=date.fromisoformat(start) if isinstance(start, str) and start else None,
        end_date=date.fromisoformat(end) if isinstance(end, str) and end else None,
        comparison=d.get("comparison"),
        attribution_dimension=d.get("attribution_dimension"),
        report_month=d.get("report_month"),
        report_region=d.get("report_region"),
        clarification=d.get("clarification"),
    )
