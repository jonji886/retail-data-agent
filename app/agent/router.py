"""Agent 路由：条件 Edge 的路由决策函数。

不写业务逻辑，只根据 state 决定下一个节点。
"""

from __future__ import annotations


from app.agent.contracts import Intent
from app.agent.state import AgentState


def route_after_parse(state: AgentState) -> str:
    """parse_request 之后：unsupported → unsupported_response，否则 → policy_check。"""
    if state.get("intent") == Intent.UNSUPPORTED or state.get("error_type"):
        return "unsupported_response"
    return "policy_check"


def route_after_policy(state: AgentState) -> str:
    """policy_check 之后：deny → permission_denied，否则 → execute_skill。"""
    if state.get("permission_decision") == "deny":
        return "permission_denied"
    return "execute_skill"


def route_after_execute(state: AgentState) -> str:
    """execute_skill 之后：失败 → error_response，否则 → validate_result。"""
    if state.get("error_type"):
        return "error_response"
    return "validate_result"


def route_after_validate(state: AgentState) -> str:
    """validate_result 之后：失败 → error_response，否则 → generate_answer。"""
    if state.get("error_type"):
        return "error_response"
    return "generate_answer"


def route_after_response(state: AgentState) -> str:
    """unsupported_response / permission_denied / error_response / generate_answer 之后 → audit。"""
    return "audit"
