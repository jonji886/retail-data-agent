"""统一 Agent State 中的 LLM 调用与确定性 fallback 记录。"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from app.observability.runtime_logging import current_request_context


def call_records(client: Any, node: str, prompt_version: str) -> List[Dict[str, Any]]:
    """把 Provider 记录的每次物理调用（含重试）转为 Agent State 记录。"""
    records = getattr(client, "call_history", None)
    if records is None:
        metadata = dict(getattr(client, "last_call_metadata", {}) or {})
        if not metadata:
            return []
        records = [{
            **metadata,
            "success": metadata.get("status", "success") == "success",
            "is_model_call": True,
            "model_call_count": int(metadata.get("model_call_count", 1)),
        }]
    return [
        {**dict(record), "node": node, "prompt_version": prompt_version}
        for record in records
    ]


def deterministic_fallback_record(
    provider: str,
    role: str,
    model: str,
    node: str,
    error_type: str,
    metadata: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """記錄 LLM 不可用後使用 deterministic 路徑的 fallback 事件。"""
    context = current_request_context()
    details = dict(metadata or {})
    return {
        "provider": details.get("provider", provider),
        "role": details.get("role", role),
        "model": details.get("model", model),
        "node": node,
        "status": "fallback",
        "success": False,
        "is_model_call": False,
        "model_call_count": 0,
        "fallback_used": True,
        "fallback_model": "deterministic",
        "reason": error_type,
        "error_type": details.get("error_type", error_type),
        "error_category": details.get("error_category"),
        "request_id": context.get("request_id"),
        "trace_id": context.get("trace_id"),
    }
