"""policy_check 节点：基于 RBAC + Data Scope 的确定性权限检查。

权限必须由程序执行，禁止用 Prompt 作为安全机制。
"""

from __future__ import annotations

import time
from pathlib import Path

from app.agent.state import AgentState
from app.tools.permission import PermissionChecker


def policy_check(state: AgentState) -> AgentState:
    root = Path(state.get("_root", "."))  # type: ignore[arg-type]
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    user_id = state.get("user_id", "user_hq")
    plan_dict = state.get("query_plan", {})
    filters = dict(plan_dict.get("filters", {}))

    checker = PermissionChecker(root)
    result = checker.check(user_id, filters)

    events = list(state.get("trace_events", []))
    events.append({
        "trace_id": trace_id, "node": "policy_check",
        "start_at": started, "end_at": time.monotonic(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status": "success" if result.success else "denied",
        "user_id": user_id,
    })

    if not result.success:
        return {
            **state,
            "permission_decision": "deny",
            "error_type": result.error_type,
            "error_message": result.error_message,
            "trace_events": events,
        }

    authorized_filters = result.data["authorized_filters"]
    # 更新 query_plan 中的 filters 为授权后的
    new_plan = dict(plan_dict)
    new_plan["filters"] = authorized_filters
    return {
        **state,
        "permission_decision": "allow",
        "query_plan": new_plan,
        "trace_events": events,
    }
