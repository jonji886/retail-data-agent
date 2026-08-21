"""Streamlit、API 和脚本共享的 Application Service 边界。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.agent.graph import run_agent
from app.agent.state import AgentState, new_state
from app.data_sources.base import DataSourceBase
from app.data_sources.factory import create_data_source
from app.observability.metrics import GLOBAL_METRICS, OperationalMetrics
from app.observability.quota import DemoQuota
from app.observability.runtime_logging import log_event
from app.quality.audit import AuditLogger


class AgentApplicationService:
    def __init__(self, root: Path, data_source: Optional[DataSourceBase] = None,
                 quota: Optional[DemoQuota] = None, metrics: Optional[OperationalMetrics] = None) -> None:
        self.root = root
        self._data_source = data_source
        self.quota = quota or DemoQuota()
        self.metrics = metrics or GLOBAL_METRICS

    @property
    def data_source(self) -> DataSourceBase:
        if self._data_source is None:
            self._data_source = create_data_source(self.root)
        return self._data_source

    def query(
        self,
        question: str,
        user_id: str = "user_hq",
        role: str = "hq_manager",
        data_scope: Optional[Dict[str, Any]] = None,
        use_llm: bool = False,
        session_id: str = "",
        client_ip: str = "",
        quota_bypass: bool = False,
        session_context: Optional[Dict[str, Any]] = None,
    ) -> AgentState:
        started = time.monotonic()
        if use_llm:
            allowed, reason = self.quota.allow(session_id or user_id, client_ip, bypass=quota_bypass)
            if not allowed:
                state = new_state(question, user_id=user_id, role=role, data_scope=data_scope)
                state["session_context"] = dict(session_context or {})
                state.update({
                    "intent": "unsupported", "error_type": "QUOTA_EXCEEDED",
                    "error_message": "Demo quota exceeded",
                    "answer": "当前 Demo 请求额度已用尽，请稍后再试。",
                    "trace_events": [{"node": "quota_check", "status": "quota_exceeded", "reason": "quota_exceeded", "latency_ms": 0}],
                })
                AuditLogger(self.root).record_agent_run(
                    request_id=state["request_id"], trace_id=state["trace_id"], question=question,
                    intent="unsupported", user_id=user_id, role=role,
                    data_scope=data_scope or {}, status="failed", error_type="QUOTA_EXCEEDED",
                    error_message="Demo quota exceeded", trace_events=state["trace_events"],
                )
                self.metrics.record_request(state, int((time.monotonic() - started) * 1000))
                log_event(
                    "agent_request_rejected",
                    request_id=state["request_id"],
                    trace_id=state["trace_id"],
                    surface="application_service",
                    error_type="QUOTA_EXCEEDED",
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return state
        try:
            state = run_agent(
                question, self.root, user_id=user_id, role=role, data_scope=data_scope,
                use_llm=use_llm, data_source=self.data_source,
                session_context=session_context,
            )
        except Exception as exc:  # noqa: BLE001
            state = new_state(question, user_id=user_id, role=role, data_scope=data_scope)
            datasource_name = getattr(self._data_source, "dialect", "unknown")
            state.update({
                "datasource": datasource_name,
                "error_type": "DATA_SOURCE_UNAVAILABLE",
                "error_message": "数据源当前不可用",
                "answer": "暂时无法连接分析数据源，请稍后重试。",
                "trace_events": [{"node": "application", "status": "error", "error_type": type(exc).__name__, "latency_ms": 0}],
            })
            AuditLogger(self.root).record_agent_run(
                request_id=state["request_id"], trace_id=state["trace_id"], question=question,
                user_id=user_id, role=role, data_scope=data_scope or {}, status="failed",
                error_type="DATA_SOURCE_UNAVAILABLE", error_message="数据源当前不可用",
                datasource=state["datasource"], trace_events=state["trace_events"],
            )
        # 页面级会话只保存最近一次问题、计划和范围，便于推荐追问继续分析。
        state["session_context"] = {
            "last_question": question,
            "last_query_plan": dict(state.get("query_plan", {})),
            "last_metric": state.get("query_plan", {}).get("metric"),
            "last_dimensions": list(state.get("query_plan", {}).get("dimensions", [])),
            "last_time_range": {
                "start_date": state.get("query_plan", {}).get("start_date"),
                "end_date": state.get("query_plan", {}).get("end_date"),
            },
            "data_scope": dict(data_scope or state.get("data_scope", {})),
        }
        self.metrics.record_request(state, int((time.monotonic() - started) * 1000))
        log_event(
            "application_request_completed",
            request_id=state["request_id"],
            trace_id=state["trace_id"],
            surface="application_service",
            error_type=state.get("error_type"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        return state

    def ready(self) -> bool:
        try:
            from app.semantic_layer.catalog import MetricCatalog
            MetricCatalog.from_file(self.root / "configs" / "metrics" / "metrics.json")
            return self.data_source.health_check()
        except Exception:  # noqa: BLE001
            return False
