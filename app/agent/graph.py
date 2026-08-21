"""LangGraph Agent Runtime：构建 StateGraph 并编译。

Graph 结构：
START → parse_request
       ├─ unsupported → unsupported_response → audit → END
       └─ policy_check
          ├─ denied → permission_denied → audit → END
          └─ execute_skill
             ├─ error → error_response → audit → END
             └─ validate_result
                ├─ error → error_response → audit → END
                └─ generate_answer → audit → END
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.audit_run import audit_run
from app.agent.nodes.execute_skill import execute_skill
from app.agent.nodes.generate_answer import generate_answer
from app.agent.nodes.parse_request import parse_request
from app.agent.nodes.policy_check import policy_check
from app.agent.nodes.validate_result import validate_result
from app.agent.router import (
    route_after_execute,
    route_after_parse,
    route_after_policy,
    route_after_validate,
)
from app.agent.state import AgentState
from app.data_sources.base import DataSourceBase
from app.data_sources.factory import create_data_source
from app.observability.runtime_logging import log_event, request_log_context


# ---------------------------------------------------------------------------
# 简单响应节点（不单独建文件，内联在此）
# ---------------------------------------------------------------------------

def unsupported_response(state: AgentState) -> AgentState:
    """对不支持意图生成用户友好回答。"""
    msg = state.get("error_message", "暂不支持该类问题。")
    answer = "无法处理该请求：%s\n\n当前支持的能力：指标查询、趋势分析、异常检测、归因分析、报告生成。" % msg
    return {**state, "answer": answer}


def permission_denied(state: AgentState) -> AgentState:
    """越权拒绝回答。"""
    msg = state.get("error_message", "权限不足。")
    answer = "权限不足，已拒绝执行：%s" % msg
    return {**state, "answer": answer}


def error_response(state: AgentState) -> AgentState:
    """错误响应回答。"""
    msg = state.get("error_message", "处理失败。")
    error_type = state.get("error_type", "UNKNOWN")
    answer = "处理失败（%s）：%s" % (error_type, msg)
    return {**state, "answer": answer}


# ---------------------------------------------------------------------------
# Graph 构建
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None):
    """构建并编译 LangGraph Agent Runtime。

    checkpointer: 可选 MemorySaver，仅用于本地 Demo thread 状态。
    明确注明：不是生产级 Durable Storage。
    """
    graph = StateGraph(AgentState)

    # 注册节点
    graph.add_node("parse_request", parse_request)
    graph.add_node("policy_check", policy_check)
    graph.add_node("execute_skill", execute_skill)
    graph.add_node("validate_result", validate_result)
    graph.add_node("generate_answer", generate_answer)
    graph.add_node("unsupported_response", unsupported_response)
    graph.add_node("permission_denied", permission_denied)
    graph.add_node("error_response", error_response)
    graph.add_node("audit", audit_run)

    # 入口
    graph.add_edge(START, "parse_request")

    # 条件路由
    graph.add_conditional_edges(
        "parse_request", route_after_parse,
        {"unsupported_response": "unsupported_response", "policy_check": "policy_check"},
    )
    graph.add_conditional_edges(
        "policy_check", route_after_policy,
        {"permission_denied": "permission_denied", "execute_skill": "execute_skill"},
    )
    graph.add_conditional_edges(
        "execute_skill", route_after_execute,
        {"error_response": "error_response", "validate_result": "validate_result"},
    )
    graph.add_conditional_edges(
        "validate_result", route_after_validate,
        {"error_response": "error_response", "generate_answer": "generate_answer"},
    )

    # 响应节点 → audit
    graph.add_edge("unsupported_response", "audit")
    graph.add_edge("permission_denied", "audit")
    graph.add_edge("error_response", "audit")
    graph.add_edge("generate_answer", "audit")

    # audit → END
    graph.add_edge("audit", END)

    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def run_agent(
    question: str,
    root: Optional[Path] = None,
    user_id: str = "user_hq",
    role: str = "hq_manager",
    data_scope: Optional[Dict[str, Any]] = None,
    use_llm: bool = False,
    llm_mode: str = "demo",
    thread_id: str = "",
    data_source: Optional[DataSourceBase] = None,
) -> AgentState:
    """运行一次完整的 Agent 流程，返回最终 state。"""
    if llm_mode not in {"demo", "evaluation"}:
        raise ValueError("llm_mode 仅支持 demo 或 evaluation")
    root = root or Path(".")
    from app.agent.state import new_state
    state = new_state(question=question, user_id=user_id, role=role,
                      data_scope=data_scope, thread_id=thread_id)
    # 注入运行时上下文（非 TypedDict 字段，但 dict 允许）
    state["_root"] = str(root)  # type: ignore[typeddict-unknown-key]
    state["_use_llm"] = use_llm  # type: ignore[typeddict-unknown-key]
    state["_llm_mode"] = llm_mode  # type: ignore[typeddict-unknown-key]
    owned_data_source = data_source is None
    selected_data_source = data_source or create_data_source(root)
    state["_data_source"] = selected_data_source  # type: ignore[typeddict-unknown-key]
    state["datasource"] = selected_data_source.dialect
    app = build_graph()
    started = time.monotonic()
    try:
        with request_log_context(
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            surface="agent_runtime",
            datasource=selected_data_source.dialect,
            use_llm=use_llm,
            llm_mode=llm_mode,
        ):
            log_event("agent_request_started", question_length=len(question))
            final_state = app.invoke(state)
            log_event(
                "agent_request_completed",
                intent=final_state.get("intent", ""),
                permission_decision=final_state.get("permission_decision", ""),
                error_type=final_state.get("error_type"),
                tool_call_count=len(final_state.get("tool_calls", [])),
                llm_call_count=len(final_state.get("llm_calls", [])),
                trace_event_count=len(final_state.get("trace_events", [])),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            final_state.pop("_root", None)  # type: ignore[misc]
            final_state.pop("_use_llm", None)  # type: ignore[misc]
            final_state.pop("_llm_mode", None)  # type: ignore[misc]
            final_state.pop("_data_source", None)  # type: ignore[misc]
            return final_state
    except Exception as exc:
        log_event(
            "agent_request_failed",
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            surface="agent_runtime",
            error_type=type(exc).__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        raise
    finally:
        if owned_data_source:
            selected_data_source.close()
