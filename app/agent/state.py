"""LangGraph Agent 统一状态定义。

只保存真正参与 Agent 生命周期的数据，避免塞入无关字段。
所有字段 total=False，允许节点按需返回部分键。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:  # Python 3.10+
    from typing import TypedDict
except ImportError:  # pragma: no cover - 兼容性兜底
    from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    # 请求
    request_id: str
    thread_id: str
    question: str

    # 用户上下文（RBAC）
    user_id: str
    role: str
    data_scope: Dict[str, Any]
    datasource: str

    # 意图与查询计划
    intent: str
    query_plan: Dict[str, Any]
    clarification_reason: Optional[str]

    # 路由
    current_skill: Optional[str]

    # 执行
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]

    # 结果
    result: Any

    # 安全
    permission_decision: Optional[str]  # allow / deny

    # 错误
    error_type: Optional[str]
    error_message: Optional[str]

    # 响应
    answer: Optional[str]

    # 可观测
    trace_id: str
    trace_events: List[Dict[str, Any]]
    llm_calls: List[Dict[str, Any]]

    # 运行时上下文（由 run_agent 注入，必须声明在 schema 中，
    # 否则 LangGraph 编译后节点收不到这些键，导致 use_llm 静默失效）
    _root: str
    _use_llm: bool
    _llm_mode: str
    _data_source: Any


def new_state(question: str, user_id: str = "user_hq", role: str = "hq_manager",
              data_scope: Optional[Dict[str, Any]] = None, thread_id: str = "",
              request_id: str = "", trace_id: str = "") -> AgentState:
    """构造一个初始 AgentState，便于上层调用。"""
    import uuid
    return AgentState(
        request_id=request_id or ("req_" + uuid.uuid4().hex[:12]),
        thread_id=thread_id or ("thread_" + uuid.uuid4().hex[:8]),
        trace_id=trace_id or ("trace_" + uuid.uuid4().hex[:12]),
        question=question,
        user_id=user_id,
        role=role,
        data_scope=data_scope if data_scope is not None else {"scope": "all"},
        tool_calls=[],
        tool_results=[],
        trace_events=[],
        llm_calls=[],
    )
