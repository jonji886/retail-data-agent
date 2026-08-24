"""硅基流动 OpenAI-compatible 客户端与四角色模型配置。

模型角色边界：

* Router：低成本意图提示，仅用于补充确定性路由，不拥有权限或 SQL 决策权；
* Main：默认生成 Query Plan、回答和报告文字；
* Reason：Main 请求失败或输出不合规时的同网关备用模型；
* Vision：预留给未来图片/多模态输入，不参与普通文本 fallback。

LLM 只负责理解和表达；权限、指标、SQL 与执行仍由确定性链路控制。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from openai import OpenAI

from app.config import load_env_file
from app.observability.runtime_logging import log_event


DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_PROVIDER = "siliconflow"
DEFAULT_MAIN_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
MODEL_ROLES = ("router", "main", "reason", "vision")

# 当前 .env 的四个正式变量名；MODEL_* 作为兼容别名保留。
ROLE_ENV_NAMES = {
    "router": ("ROUTER", "MODEL_ROUTER"),
    "main": ("MAIN", "MODEL_MAIN"),
    "reason": ("REASON", "MODEL_REASON"),
    "vision": ("VISION", "MODEL_VISION"),
}

# 旧三变量仅用于兼容此前的本地配置；新项目配置应使用 ROUTER/MAIN/REASON/VISION。
LEGACY_MAIN_ENV = "MODEL_DEEPSEEK"
LEGACY_REASON_ENVS = ("MODEL_QWEN", "MODEL_GLM")


@dataclass(frozen=True)
class SiliconFlowConfig:
    """从环境变量解析出的硅基流动四角色模型配置。"""

    api_key: str
    provider: str = DEFAULT_PROVIDER
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MAIN_MODEL
    timeout_seconds: float = 60.0
    max_tokens: int = 1200
    max_retries: int = 1
    fallback_model: str = "deterministic"
    router_model: str = ""
    # 留空表示沿用兼容字段 model；from_env 会同时填充两者。
    main_model: str = ""
    reason_model: str = ""
    vision_model: str = ""
    fallback_provider: str = DEFAULT_PROVIDER

    @property
    def fallback_models(self) -> Tuple[str, ...]:
        """兼容旧的监控/调用方命名；文本 fallback 只有 Reason。"""
        return (self.reason_model,) if self.reason_model else ()

    def model_for(self, role: str) -> str:
        """按角色返回模型；Vision 未配置时明确报错。"""
        if role not in MODEL_ROLES:
            raise ValueError("未知 LLM 模型角色：%s" % role)
        model = {
            "router": self.router_model,
            "main": self.main_model or self.model,
            "reason": self.reason_model,
            "vision": self.vision_model,
        }[role]
        if not model:
            raise RuntimeError("未配置 MODEL_%s 模型" % role.upper())
        return model

    @classmethod
    def from_env(cls, root: Path, mode: str = "demo") -> "SiliconFlowConfig":
        load_env_file(root / ".env")
        if mode not in {"demo", "evaluation"}:
            raise RuntimeError("LLM 配置 mode 仅支持 demo 或 evaluation")

        api_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未找到 SILICONFLOW_API_KEY，请在本地 .env 或运行环境中配置")
        base_url = os.getenv("SILICONFLOW_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL

        configured_main_model = _role_env("main") or _env_value(LEGACY_MAIN_ENV)
        main_model = configured_main_model or DEFAULT_MAIN_MODEL
        reason_model = _role_env("reason") or _first_env_value(LEGACY_REASON_ENVS)
        router_model = _role_env("router")
        vision_model = _role_env("vision")

        configured_model = _env_value("LLM_MODEL")
        if mode == "evaluation":
            main_model = _env_value("EVAL_LLM_MODEL") or configured_model or configured_main_model
            if not main_model:
                raise RuntimeError("真实 Evaluation 必须使用固定的具体 Main 模型")
        elif configured_model:
            main_model = configured_model

        try:
            timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1200"))
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        except ValueError as exc:
            raise RuntimeError("LLM_TIMEOUT_SECONDS 必须是数字，LLM_MAX_TOKENS 必须是整数") from exc
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise RuntimeError("LLM_TIMEOUT_SECONDS 和 LLM_MAX_TOKENS 必须大于 0")
        if max_retries < 0 or max_retries > 2:
            raise RuntimeError("LLM_MAX_RETRIES 必须在 0 到 2 之间")

        return cls(
            api_key=api_key,
            provider=DEFAULT_PROVIDER,
            base_url=base_url,
            model=main_model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            max_retries=max_retries,
            fallback_model=_env_value("LLM_FALLBACK_MODEL") or "deterministic",
            router_model=router_model,
            main_model=main_model,
            reason_model=reason_model,
            vision_model=vision_model,
            fallback_provider=DEFAULT_PROVIDER,
        )

    @classmethod
    def is_configured(cls, root: Path, mode: str = "demo") -> bool:
        """判断主模型是否可用；Router/Reason/Vision 可按角色独立检查。"""
        load_env_file(root / ".env")
        if not os.getenv("SILICONFLOW_API_KEY", "").strip():
            return False
        if mode == "evaluation":
            return bool(
                _env_value("EVAL_LLM_MODEL")
                or _env_value("LLM_MODEL")
                or _role_env("main")
                or _env_value(LEGACY_MAIN_ENV)
            )
        return bool(_role_env("main") or _env_value(LEGACY_MAIN_ENV) or DEFAULT_MAIN_MODEL)

    @classmethod
    def is_role_configured(cls, root: Path, role: str, mode: str = "demo") -> bool:
        """不创建客户端地判断某个模型角色是否已配置。"""
        if role not in MODEL_ROLES:
            return False
        load_env_file(root / ".env")
        if not os.getenv("SILICONFLOW_API_KEY", "").strip():
            return False
        if role == "main":
            return cls.is_configured(root, mode=mode)
        if role == "reason":
            return bool(_role_env("reason") or _first_env_value(LEGACY_REASON_ENVS))
        return bool(_role_env(role))


class SiliconFlowClient:
    """支持角色选择、有限重试和 Main → Reason 故障切换的客户端。"""

    def __init__(self, config: SiliconFlowConfig) -> None:
        self.config = config
        self.last_call_metadata: Dict[str, Any] = {}
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )

    def _request(self, response_format: Optional[Dict[str, str]], system_prompt: str,
                 user_prompt: str, temperature: float, max_tokens: int, role: str) -> str:
        started = time.monotonic()
        primary_model = self.config.model_for(role)
        primary_content, primary_metadata, primary_error = self._request_model(
            primary_model,
            role,
            response_format,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
            max_retries=self.config.max_retries,
        )
        if primary_content is not None:
            self.last_call_metadata = {
                **primary_metadata,
                "fallback_used": False,
                "fallback_available": role == "main" and bool(self.config.reason_model),
                "fallback_attempted": False,
                "fallback_model": None,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
            self._log_completed(self.last_call_metadata)
            return primary_content

        # Reason 只作为 Main 的备用，不把 Router/Vision 混入文本 fallback。
        reason_model = self.config.reason_model if role == "main" else ""
        if reason_model and reason_model != primary_model:
            log_event(
                "llm_fallback_started",
                from_provider=self.config.provider,
                from_model=primary_model,
                from_role=role,
                to_provider=self.config.provider,
                to_model=reason_model,
                to_role="reason",
                primary_error_type=type(primary_error).__name__ if primary_error else "unknown",
            )
            fallback_content, fallback_metadata, fallback_error = self._request_model(
                reason_model,
                "reason",
                response_format,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                max_retries=0,
            )
            if fallback_content is not None:
                self.last_call_metadata = {
                    **fallback_metadata,
                    "fallback_used": True,
                    "fallback_available": True,
                    "fallback_attempted": True,
                    "fallback_from": primary_model,
                    "fallback_from_model": primary_model,
                    "fallback_provider": self.config.provider,
                    "fallback_model": reason_model,
                    "fallback_reason": primary_metadata.get("error_category") or _error_category(primary_error),
                    "primary_error_category": primary_metadata.get("error_category"),
                    "primary_retry_count": primary_metadata.get("retry_count", 0),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
                self._log_completed(self.last_call_metadata)
                return fallback_content
            last_error = fallback_error or primary_error
        else:
            last_error = primary_error
            log_event(
                "llm_fallback_skipped",
                from_provider=self.config.provider,
                from_model=primary_model,
                from_role=role,
                reason="reason_model_not_configured_or_not_applicable",
            )

        self.last_call_metadata = {
            **primary_metadata,
            "status": "error",
            "error_type": type(last_error).__name__ if last_error else "unknown",
            "error_category": _error_category(last_error),
            "fallback_available": bool(reason_model),
            "fallback_attempted": bool(reason_model),
            "fallback_provider": self.config.provider if reason_model else None,
            "fallback_model": reason_model or None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
        log_event(
            "llm_request_failed",
            provider=self.config.provider,
            role=role,
            model=primary_model,
            error_type=self.last_call_metadata["error_type"],
            fallback_available=self.last_call_metadata["fallback_available"],
            fallback_attempted=self.last_call_metadata["fallback_attempted"],
            latency_ms=self.last_call_metadata["latency_ms"],
        )
        if reason_model:
            exc = RuntimeError("硅基流动 Main 与 Reason 模型请求均失败")
        else:
            exc = RuntimeError("硅基流动 %s 模型请求失败，且未配置可用 Reason fallback" % role)
        setattr(exc, "llm_metadata", dict(self.last_call_metadata))
        raise exc from last_error

    def _request_model(
        self,
        model: str,
        role: str,
        response_format: Optional[Dict[str, str]],
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        max_retries: int,
    ) -> Tuple[Optional[str], Dict[str, Any], Optional[Exception]]:
        """调用单个角色模型，返回内容、审计元数据和最后一个异常。"""
        started = time.monotonic()
        retries = 0
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                response = self._client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content if response.choices else None
                if not content:
                    raise RuntimeError("empty_response")
                usage = getattr(response, "usage", None)
                metadata = {
                    "provider": self.config.provider,
                    "role": role,
                    "model": model,
                    "retry_count": retries,
                    "status": "success",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "input_tokens": getattr(usage, "prompt_tokens", None),
                    "output_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
                log_event(
                    "llm_provider_request",
                    provider=self.config.provider,
                    role=role,
                    model=model,
                    outcome="success",
                    attempt=attempt + 1,
                    retry_count=retries,
                    latency_ms=metadata["latency_ms"],
                    input_tokens=metadata["input_tokens"],
                    output_tokens=metadata["output_tokens"],
                    total_tokens=metadata["total_tokens"],
                )
                return content, metadata, None
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                category = _error_category(exc)
                log_event(
                    "llm_provider_request",
                    provider=self.config.provider,
                    role=role,
                    model=model,
                    outcome="error",
                    attempt=attempt + 1,
                    retry_count=retries,
                    error_type=type(exc).__name__,
                    error_category=category,
                    http_status=getattr(exc, "status_code", None),
                    error_code=getattr(exc, "code", None),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                if attempt < max_retries:
                    retries += 1
                    time.sleep(min(0.25 * (2 ** attempt), 1.0))
        return None, {
            "provider": self.config.provider,
            "role": role,
            "model": model,
            "retry_count": retries,
            "status": "error",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error_type": type(last_exc).__name__ if last_exc else "unknown",
            "error_category": _error_category(last_exc),
        }, last_exc

    def _log_completed(self, metadata: Dict[str, Any]) -> None:
        log_event(
            "llm_request_completed",
            provider=metadata.get("provider", self.config.provider),
            role=metadata.get("role"),
            model=metadata.get("model", self.config.model),
            fallback_used=metadata.get("fallback_used", False),
            fallback_model=metadata.get("fallback_model"),
            latency_ms=metadata.get("latency_ms"),
        )

    def complete_json(self, system_prompt: str, user_prompt: str, role: str = "main") -> str:
        return self._request(
            {"type": "json_object"}, system_prompt, user_prompt, 0, self.config.max_tokens, role
        )

    def complete_text(self, system_prompt: str, user_prompt: str,
                      max_tokens: Optional[int] = None, role: str = "main") -> str:
        return self._request(
            None, system_prompt, user_prompt, 0.2, max_tokens or self.config.max_tokens, role
        ).strip()

    def route_intent(self, question: str) -> str:
        """用低成本 Router 返回受限意图枚举；调用方仍需本地校验。"""
        content = self.complete_json(
            "你是经营分析系统的低成本意图路由器。只输出 JSON，不能生成 SQL。\n"
            "允许的 intent：metric_query、trend_analysis、attribution_analysis、"
            "anomaly_analysis、report_generation、unsupported。",
            json.dumps({"question": question}, ensure_ascii=False),
            role="router",
        )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Router 没有返回合法 JSON") from exc
        intent = payload.get("intent") if isinstance(payload, dict) else None
        allowed = {
            "metric_query", "trend_analysis", "attribution_analysis",
            "anomaly_analysis", "report_generation", "unsupported",
        }
        if intent not in allowed:
            raise RuntimeError("Router 返回了未注册 intent：%s" % intent)
        return intent


def provider_status(root: Path) -> Dict[str, Any]:
    """返回不含密钥的硅基流动四角色运行状态。"""
    load_env_file(root / ".env")
    main_model = _role_env("main") or _env_value(LEGACY_MAIN_ENV) or DEFAULT_MAIN_MODEL
    reason_model = _role_env("reason") or _first_env_value(LEGACY_REASON_ENVS)
    router_model = _role_env("router")
    vision_model = _role_env("vision")
    key_configured = bool(os.getenv("SILICONFLOW_API_KEY", "").strip())
    return {
        "primary_provider": DEFAULT_PROVIDER,
        "primary_model_role": "main",
        "model": main_model,
        "status": "available" if key_configured else "not_configured",
        "router_model": router_model,
        "main_model": main_model,
        "reason_model": reason_model,
        "vision_model": vision_model,
        "router_configured": bool(key_configured and router_model),
        "fallback_provider": DEFAULT_PROVIDER if key_configured and reason_model else "disabled",
        "fallback_models": [reason_model] if reason_model else [],
        "fallback_configured": bool(key_configured and reason_model),
    }


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def _role_env(role: str) -> str:
    """读取正式角色变量，并兼容早期 MODEL_* 命名。"""
    return _first_env_value(ROLE_ENV_NAMES[role])


def _first_env_value(names: Iterable[str]) -> str:
    for name in names:
        value = _env_value(name)
        if value:
            return value
    return ""


def _error_category(exc: Optional[Exception]) -> str:
    """把 SDK 异常归一为可审计、可展示的故障类别。"""
    if exc is None:
        return "unknown"
    status = getattr(exc, "status_code", None)
    name = type(exc).__name__.lower()
    if status == 401 or "authentication" in name or "permission" in name:
        return "invalid_api_key"
    if status == 429 or "rate" in name or "ratelimit" in name:
        return "rate_limit"
    if "timeout" in name or isinstance(exc, TimeoutError):
        return "timeout"
    if "json" in name or "response" in name or str(exc) == "empty_response":
        return "invalid_response"
    return "provider_error"
