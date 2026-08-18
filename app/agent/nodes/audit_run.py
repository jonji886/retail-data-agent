"""audit_run 节点：统一记录每次 Agent Run 的审计信息与 trace。

不记录 API Key / Secret / Password / Token。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from app.agent.state import AgentState
from app.quality.audit import AuditLogger


def audit_run(state: AgentState) -> AgentState:
    root = Path(state.get("_root", "."))  # type: ignore[arg-type]
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    events = list(state.get("trace_events", []))

    logger = AuditLogger(root)
    question = state.get("question", "")
    intent = state.get("intent", "")
    skill = state.get("current_skill", "")
    plan = state.get("query_plan", {})
    status = "failed" if state.get("error_type") else "success"
    error_type = state.get("error_type")
    error_message = state.get("error_message")

    # 收集 SQL
    sql_list = []
    for tr in state.get("tool_results", []):
        data = tr.get("data") or {}
        if isinstance(data, dict):
            if data.get("sql"):
                sql_list.append(data["sql"])

    # 记录到审计日志
    event_id = logger.record_agent_run(
        request_id=state.get("request_id", ""),
        trace_id=trace_id,
        question=question,
        intent=intent,
        skill=skill,
        query_plan=plan,
        user_id=state.get("user_id", ""),
        role=state.get("role", ""),
        data_scope=state.get("data_scope", {}),
        permission_decision=state.get("permission_decision", ""),
        status=status,
        error_type=error_type,
        error_message=error_message,
        sql_list=sql_list,
        tool_calls=state.get("tool_calls", []),
        trace_events=events,
        llm_calls=state.get("llm_calls", []),
    )

    events.append({
        "trace_id": trace_id, "node": "audit_run",
        "start_at": started, "end_at": time.monotonic(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status": "success", "audit_event_id": event_id,
    })

    return {**state, "trace_events": events}
