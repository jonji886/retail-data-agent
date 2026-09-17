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
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver

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
from app.agent.state import AgentRuntimeContext, AgentState
from app.config import CheckpointConfig
from app.data_sources.base import DataSourceBase
from app.data_sources.factory import create_data_source
from app.infrastructure.checkpoint.factory import checkpoint_session
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

def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    interrupt_after: Optional[Sequence[str]] = None,
):
    """构建并编译 LangGraph Agent Runtime。

    ``checkpointer`` 由基础设施工厂提供，业务节点不感知具体后端。
    ``interrupt_after`` 是可控的 Demo / Test 故障边界，生产默认为空。
    """
    graph = StateGraph(AgentState, context_schema=AgentRuntimeContext)

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

    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)


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
    session_context: Optional[Dict[str, Any]] = None,
    checkpoint_config: Optional[CheckpointConfig] = None,
) -> AgentState:
    """运行一次完整的 Agent 流程，返回最终 state。"""
    if llm_mode not in {"demo", "evaluation"}:
        raise ValueError("llm_mode 仅支持 demo 或 evaluation")
    root = root or Path(".")
    from app.agent.state import new_state
    selected_checkpoint = checkpoint_config or CheckpointConfig.from_env(root)
    state = new_state(question=question, user_id=user_id, role=role,
                      data_scope=data_scope, thread_id=thread_id)
    state["session_context"] = dict(session_context or {})
    # 仅注入可序列化运行元数据；连接对象通过 LangGraph runtime context 传递。
    state["_root"] = str(root)  # type: ignore[typeddict-unknown-key]
    state["_use_llm"] = use_llm  # type: ignore[typeddict-unknown-key]
    state["_llm_mode"] = llm_mode  # type: ignore[typeddict-unknown-key]
    owned_data_source = data_source is None
    selected_data_source = data_source or create_data_source(root)
    state["datasource"] = selected_data_source.dialect
    interrupt_after = _interrupt_after(selected_checkpoint)
    runtime_context: AgentRuntimeContext = {
        "root": root,
        "use_llm": use_llm,
        "llm_mode": llm_mode,
        "data_source": selected_data_source,
    }
    graph_config = _thread_config(state["thread_id"])
    started = time.monotonic()
    try:
        with checkpoint_session(root, selected_checkpoint) as checkpointer:
            app = build_graph(checkpointer=checkpointer, interrupt_after=interrupt_after)
            with request_log_context(
                request_id=state["request_id"],
                trace_id=state["trace_id"],
                surface="agent_runtime",
                datasource=selected_data_source.dialect,
                use_llm=use_llm,
                llm_mode=llm_mode,
            ):
                log_event("agent_request_started", question_length=len(question))
                final_state = app.invoke(state, graph_config, context=runtime_context)
                snapshot = app.get_state(graph_config) if checkpointer else None
                log_event(
                    "agent_request_completed",
                    intent=final_state.get("intent", ""),
                    permission_decision=final_state.get("permission_decision", ""),
                    error_type=final_state.get("error_type"),
                    tool_call_count=len(final_state.get("tool_calls", [])),
                    llm_call_count=len(final_state.get("llm_calls", [])),
                    trace_event_count=len(final_state.get("trace_events", [])),
                    checkpoint_next_nodes=list(snapshot.next) if snapshot else [],
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return _public_state(final_state)
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


def resume_agent(
    root: Path,
    thread_id: str,
    data_source: Optional[DataSourceBase] = None,
    checkpoint_config: Optional[CheckpointConfig] = None,
) -> AgentState:
    """在新 Graph 实例中从同一 thread 的最新 Checkpoint 继续执行。

    已完成的 thread 不会再次 invoke；直接返回已持久化的最终 State。
    """
    if not thread_id.strip():
        raise ValueError("resume 必须提供非空 thread_id")
    selected_checkpoint = checkpoint_config or CheckpointConfig.from_env(root)
    if not selected_checkpoint.enabled:
        raise RuntimeError("resume 需要启用 Checkpoint")
    # resume 阶段必须关闭 start 阶段的 interrupt，避免在同一安全边界再次暂停。
    resume_checkpoint = replace(
        selected_checkpoint,
        failure_injection_enabled=False,
        fail_after_node="",
    )
    graph_config = _thread_config(thread_id)

    with checkpoint_session(root, resume_checkpoint) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        snapshot = app.get_state(graph_config)
        if snapshot is None:
            raise ValueError("找不到 thread_id=%s 的 Checkpoint" % thread_id)
        if not snapshot.next:
            return _public_state(snapshot.values)

        owned_data_source = data_source is None
        selected_data_source = data_source or create_data_source(root)
        try:
            values = snapshot.values
            runtime_context: AgentRuntimeContext = {
                "root": root,
                "use_llm": bool(values.get("_use_llm", False)),
                "llm_mode": str(values.get("_llm_mode", "demo")),
                "data_source": selected_data_source,
            }
            with request_log_context(
                request_id=values.get("request_id", ""),
                trace_id=values.get("trace_id", ""),
                surface="agent_runtime_resume",
                datasource=selected_data_source.dialect,
            ):
                final_state = app.invoke(None, graph_config, context=runtime_context)
            return _public_state(final_state)
        finally:
            if owned_data_source:
                selected_data_source.close()


def inspect_checkpoint(
    root: Path,
    thread_id: str,
    checkpoint_config: Optional[CheckpointConfig] = None,
) -> Dict[str, Any]:
    """通过 LangGraph StateSnapshot 查询 thread 当前状态与历史。"""
    if not thread_id.strip():
        raise ValueError("inspect 必须提供非空 thread_id")
    selected_checkpoint = checkpoint_config or CheckpointConfig.from_env(root)
    if not selected_checkpoint.enabled:
        raise RuntimeError("inspect 需要启用 Checkpoint")

    with checkpoint_session(root, selected_checkpoint) as checkpointer:
        app = build_graph(checkpointer=checkpointer)
        graph_config = _thread_config(thread_id)
        snapshot = app.get_state(graph_config)
        if snapshot is None:
            return {
                "thread_id": thread_id,
                "status": "not_found",
                "checkpoint_count": 0,
                "history": [],
            }

        history = list(app.get_state_history(graph_config))
        return {
            "thread_id": thread_id,
            "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id", ""),
            "current_node": _last_trace_node(snapshot.values),
            "next_nodes": list(snapshot.next),
            "updated_at": snapshot.created_at,
            "checkpoint_count": len(history),
            "status": "completed" if not snapshot.next else "paused",
            "state": _public_state(snapshot.values),
            "history": [_history_item(item, index + 1) for index, item in enumerate(reversed(history))],
        }


def _thread_config(thread_id: str) -> Dict[str, Dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def _interrupt_after(config: CheckpointConfig) -> Optional[List[str]]:
    if not config.failure_injection_enabled:
        return None
    return [config.fail_after_node]


def _public_state(state: Dict[str, Any]) -> AgentState:
    """移除运行时注入字段；这些字段仍可作为可序列化恢复上下文存在于 Checkpoint。"""
    cleaned = dict(state)
    for key in ("_root", "_use_llm", "_llm_mode", "_data_source"):
        cleaned.pop(key, None)
    return cleaned  # type: ignore[return-value]


def _last_trace_node(state: Dict[str, Any]) -> str:
    events = state.get("trace_events") or []
    for event in reversed(events):
        if event.get("node"):
            return str(event["node"])
    return "START"


def _history_item(snapshot: Any, index: int) -> Dict[str, Any]:
    return {
        "number": index,
        "checkpoint_id": snapshot.config["configurable"].get("checkpoint_id", ""),
        "node": _last_trace_node(snapshot.values),
        "next_nodes": list(snapshot.next),
        "step": snapshot.metadata.get("step"),
        "source": snapshot.metadata.get("source"),
        "updated_at": snapshot.created_at,
    }
