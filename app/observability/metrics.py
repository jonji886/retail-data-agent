"""进程内 Operational Metrics。

MVP 不引入 Prometheus/Redis；指标用于健康检查、调试页和一次请求的定位。
"""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any, Dict, Mapping


class OperationalMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter[str] = Counter()
        self._latency_totals: Counter[str] = Counter()
        self._labels: Dict[str, str] = {}

    def record_request(self, state: Mapping[str, Any], latency_ms: int) -> None:
        with self._lock:
            self._counters["request_count"] += 1
            if state.get("error_type"):
                self._counters["failure_count"] += 1
            else:
                self._counters["success_count"] += 1
            if state.get("error_type") == "QUOTA_EXCEEDED":
                self._counters["quota_exceeded_count"] += 1
            if state.get("permission_decision") == "deny":
                self._counters["permission_deny_count"] += 1
            if state.get("intent") == "unsupported":
                self._counters["unsupported_count"] += 1
            fallback_count = sum(1 for item in state.get("llm_calls", []) if item.get("status") == "fallback")
            self._counters["fallback_count"] += fallback_count
            for item in state.get("llm_calls", []):
                if item.get("provider"):
                    self._labels["provider"] = str(item["provider"])
                if item.get("model"):
                    self._labels["model"] = str(item["model"])
            if state.get("datasource"):
                self._labels["datasource"] = str(state["datasource"])
            self._latency_totals["request_latency_ms"] += latency_ms
            for event in state.get("trace_events", []):
                node = event.get("node")
                value = int(event.get("latency_ms") or 0)
                if node == "parse_request":
                    self._latency_totals["llm_latency_ms"] += value
                if node == "execute_skill":
                    self._latency_totals["tool_latency_ms"] += value
                if node in {"execute_skill", "validate_result"}:
                    self._latency_totals["database_latency_ms"] += value

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            requests = counters.get("request_count", 0)
            fallbacks = counters.get("fallback_count", 0)
            return {
                **counters,
                "success_rate": counters.get("success_count", 0) / requests if requests else 0.0,
                "fallback_rate": fallbacks / requests if requests else 0.0,
                "latency_totals_ms": dict(self._latency_totals),
                **self._labels,
            }


GLOBAL_METRICS = OperationalMetrics()
