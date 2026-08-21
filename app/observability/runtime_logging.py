"""面向 Render Application Logs 的轻量结构化运行日志。

日志只记录请求关联 ID、模型调用状态与性能元数据，不记录问题正文、Prompt、
API Key、Authorization 或数据库连接串。Render 会收集 stdout/stderr，因此使用
标准输出处理器即可在后台的 Application logs 中搜索这些事件。
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator


LOGGER_NAME = "retail_data_agent.runtime"
_CONTEXT: ContextVar[Dict[str, Any]] = ContextVar("runtime_log_context", default={})
_SENSITIVE_FIELD_NAMES = {
    "api_key", "authorization", "password", "secret", "token",
    "database_url", "question", "prompt",
}


def _logger() -> logging.Logger:
    """返回仅输出 JSON 事件的 logger，避免依赖宿主框架的 logging 配置。"""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def _safe_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """确保任何调用方误传敏感字段时也不会写入日志。"""
    safe: Dict[str, Any] = {}
    for key, value in fields.items():
        normalized = key.lower()
        if (
            normalized in _SENSITIVE_FIELD_NAMES
            or normalized.endswith("_api_key")
            or normalized.endswith("_password")
            or normalized.endswith("_secret")
            or normalized.endswith("_database_url")
        ):
            safe[key] = "[REDACTED]"
        elif value is None or isinstance(value, (bool, int, float, str)):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


@contextmanager
def request_log_context(**fields: Any) -> Iterator[Dict[str, Any]]:
    """为一次业务请求绑定关联信息，传递给其中所有 LLM 调用日志。"""
    context = dict(_CONTEXT.get())
    context.update(_safe_fields(dict(fields)))
    context.setdefault("request_id", "req_" + uuid.uuid4().hex[:12])
    context.setdefault("trace_id", "trace_" + uuid.uuid4().hex[:16])
    token = _CONTEXT.set(context)
    try:
        yield dict(context)
    finally:
        _CONTEXT.reset(token)


def log_event(event: str, **fields: Any) -> None:
    """向 Render 输出可搜索的单行 JSON 日志。"""
    payload = {"event": event, **_CONTEXT.get(), **_safe_fields(dict(fields))}
    _logger().info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
