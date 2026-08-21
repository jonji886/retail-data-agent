"""OpenAI-compatible LLM 客户端。

类名保留 ``OpenRouter*`` 是为了兼容现有调用方；运行时 Provider 已抽象为
DeepSeek 主 Provider + 可选 OpenRouter fallback。LLM 只负责理解和表达，权限、
指标、SQL 与执行仍由确定性链路控制。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Tuple
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from app.config import load_env_file
from app.observability.runtime_logging import log_event


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_PROVIDER = "deepseek"
LEGACY_OPENROUTER_MODEL = "openrouter/free"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_PROVIDER = "deepseek"


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    # dataclass 直接构造时保留 openrouter 作为兼容默认；from_env 的产品默认
    # 是 DeepSeek，避免破坏既有单测和第三方脚本显式构造的旧配置。
    provider: str = "openrouter"
    base_url: str = DEFAULT_BASE_URL
    model: str = LEGACY_OPENROUTER_MODEL
    timeout_seconds: float = 60.0
    max_tokens: int = 1200
    max_retries: int = 1
    fallback_model: str = "deterministic"
    fallback_models: Tuple[str, ...] = ()
    http_referer: str = ""
    app_title: str = "Retail Data Agent"
    # DeepSeek 是 OpenRouter 请求失败后的跨 Provider fallback；不参与
    # OpenRouter 的 extra_body 模型路由。
    deepseek_api_key: str = ""
    deepseek_base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    # DeepSeek 主链路使用 OpenRouter 作为可选 fallback；旧配置仍可使用
    # deepseek_* 字段表示 OpenRouter → DeepSeek 的 fallback。
    openrouter_api_key: str = ""
    openrouter_base_url: str = DEFAULT_BASE_URL
    openrouter_model: str = LEGACY_OPENROUTER_MODEL
    fallback_provider: str = "openrouter"

    @classmethod
    def from_env(cls, root: Path, mode: str = "demo") -> "OpenRouterConfig":
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        if provider not in {"deepseek", "openrouter"}:
            raise RuntimeError("LLM_PROVIDER 仅支持 deepseek 或 openrouter")
        if mode not in {"demo", "evaluation"}:
            raise RuntimeError("LLM 配置 mode 仅支持 demo 或 evaluation")
        configured_model = os.getenv("LLM_MODEL", "").strip()
        if provider == "deepseek" and configured_model in {"", LEGACY_OPENROUTER_MODEL}:
            configured_model = ""
        openrouter_model = (
            configured_model
            or os.getenv("OPENROUTER_MODEL", "").strip()
            or LEGACY_OPENROUTER_MODEL
        )
        deepseek_model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL
        if mode == "evaluation":
            # DeepSeek 的 deepseek-chat 是固定模型；仍允许显式 EVAL_LLM_MODEL
            # 覆盖，保证评测报告记录的模型与实际调用一致。
            model = os.getenv("EVAL_LLM_MODEL", "").strip() or (
                deepseek_model if provider == "deepseek" else openrouter_model
            )
            if not model or model == LEGACY_OPENROUTER_MODEL or model.endswith("/free"):
                raise RuntimeError("真实 Evaluation 必须使用固定的具体模型，不能使用 openrouter/free")
        else:
            model = configured_model or (deepseek_model if provider == "deepseek" else openrouter_model)
        try:
            timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60")))
            max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "1200"))
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        except ValueError as exc:
            raise RuntimeError(
                "LLM_TIMEOUT_SECONDS 必须是数字，OPENROUTER_MAX_TOKENS 必须是整数"
            ) from exc
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise RuntimeError("LLM_TIMEOUT_SECONDS 和 OPENROUTER_MAX_TOKENS 必须大于 0")
        if max_retries < 0 or max_retries > 2:
            raise RuntimeError("LLM_MAX_RETRIES 必须在 0 到 2 之间")
        fallback_models = _parse_model_list(os.getenv("OPENROUTER_FALLBACK_MODELS", ""))
        deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if provider == "deepseek":
            api_key = deepseek_api_key
            if not api_key:
                raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在本地 .env 或运行环境中配置")
            base_url = os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL
            fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "openrouter").strip().lower() or "openrouter"
            if fallback_provider != "openrouter":
                raise RuntimeError("LLM_FALLBACK_PROVIDER 当前仅支持 openrouter")
        else:
            api_key = openrouter_api_key
            if not api_key:
                raise RuntimeError("未找到 OPENROUTER_API_KEY，请在本地 .env 或运行环境中配置")
            base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
            fallback_provider = "deepseek"
        return cls(
            api_key=api_key,
            provider=provider,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            max_retries=max_retries,
            fallback_model=os.getenv("LLM_FALLBACK_MODEL", "deterministic").strip() or "deterministic",
            fallback_models=fallback_models,
            http_referer=os.getenv("OPENROUTER_HTTP_REFERER", "").strip(),
            app_title=os.getenv("OPENROUTER_APP_TITLE", "Retail Data Agent").strip() or "Retail Data Agent",
            deepseek_api_key=deepseek_api_key,
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL,
            deepseek_model=deepseek_model,
            openrouter_api_key=openrouter_api_key,
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            openrouter_model=openrouter_model,
            fallback_provider=fallback_provider,
        )

    @classmethod
    def is_configured(cls, root: Path, mode: str = "demo") -> bool:
        """判断当前进程是否已提供主 Provider 配置，不暴露 Key。"""
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        primary_key = os.getenv("DEEPSEEK_API_KEY", "").strip() if provider == "deepseek" else os.getenv("OPENROUTER_API_KEY", "").strip()
        if provider not in {"deepseek", "openrouter"} or not primary_key:
            return False
        if mode == "evaluation":
            model = os.getenv("EVAL_LLM_MODEL", "").strip() or os.getenv(
                "DEEPSEEK_MODEL" if provider == "deepseek" else "OPENROUTER_MODEL", ""
            ).strip() or (DEFAULT_MODEL if provider == "deepseek" else LEGACY_OPENROUTER_MODEL)
            return bool(model) and model != LEGACY_OPENROUTER_MODEL and not model.endswith("/free")
        return True


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config
        self.last_call_metadata: Dict[str, Any] = {}
        headers = {}
        if config.http_referer:
            headers["HTTP-Referer"] = config.http_referer
        if config.app_title:
            headers["X-OpenRouter-Title"] = config.app_title
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
            default_headers=headers or None,
        )
        self._deepseek_client: Optional[OpenAI] = None
        self._openrouter_client: Optional[OpenAI] = None
        if config.provider == DEEPSEEK_PROVIDER and config.openrouter_api_key:
            self._openrouter_client = OpenAI(
                api_key=config.openrouter_api_key,
                base_url=config.openrouter_base_url,
                timeout=config.timeout_seconds,
                default_headers=headers or None,
            )
        # 保留旧属性：显式构造 OpenRouterConfig(provider="openrouter",
        # deepseek_api_key=...) 的调用方仍然得到 OpenRouter → DeepSeek failover。
        if config.provider == "openrouter" and config.deepseek_api_key:
            self._deepseek_client = OpenAI(
                api_key=config.deepseek_api_key,
                base_url=config.deepseek_base_url,
                timeout=config.timeout_seconds,
            )

    def _request(self, response_format: Optional[Dict[str, str]], system_prompt: str,
                 user_prompt: str, temperature: float, max_tokens: int) -> str:
        started = time.monotonic()
        content, metadata, error = self._request_provider(
            self._client, self.config.provider, self.config.model,
            response_format, system_prompt, user_prompt, temperature, max_tokens,
            include_openrouter_routing=True,
        )
        if content is not None:
            self.last_call_metadata = {
                **metadata,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
            log_event(
                "llm_request_completed",
                provider=self.config.provider,
                model=self.config.model,
                fallback_used=False,
                latency_ms=self.last_call_metadata["latency_ms"],
            )
            return content

        # 主 Provider 已按 max_retries 重试仍失败时，才切换可选 fallback。
        fallback_error: Optional[Exception] = None
        fallback_client, fallback_provider, fallback_model = self._fallback_target()
        if fallback_client is not None:
            log_event(
                "llm_fallback_started",
                from_provider=self.config.provider,
                to_provider=fallback_provider,
                primary_error_type=type(error).__name__ if error else "unknown",
            )
            fallback_content, fallback_metadata, fallback_error = self._request_provider(
                fallback_client, fallback_provider, fallback_model,
                response_format, system_prompt, user_prompt, temperature, max_tokens,
                include_openrouter_routing=False,
                max_retries=0,
            )
            if fallback_content is not None:
                self.last_call_metadata = {
                    **fallback_metadata,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "fallback_used": True,
                    "fallback_from": self.config.provider,
                    "fallback_reason": metadata.get("error_category") or (type(error).__name__ if error else "provider_error"),
                    "primary_error_category": metadata.get("error_category"),
                    "primary_retry_count": metadata.get("retry_count", 0),
                }
                log_event(
                    "llm_request_completed",
                    provider=fallback_provider,
                    model=fallback_model,
                    fallback_used=True,
                    fallback_from=self.config.provider,
                    latency_ms=self.last_call_metadata["latency_ms"],
                )
                return fallback_content
            error = fallback_error or error
        else:
            log_event(
                "llm_fallback_skipped",
                from_provider=self.config.provider,
                reason="fallback_provider_not_configured",
            )

        self.last_call_metadata = {
            **metadata,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "status": "error",
            "error_type": type(error).__name__ if error else "unknown",
            "error_category": _error_category(error),
            "fallback_available": fallback_client is not None,
            "fallback_attempted": fallback_client is not None,
            "fallback_provider": fallback_provider if fallback_client is not None else None,
            "fallback_error_type": type(fallback_error).__name__ if fallback_error else None,
            "fallback_error_category": _error_category(fallback_error) if fallback_error else None,
        }
        log_event(
            "llm_request_failed",
            provider=self.config.provider,
            model=self.config.model,
            error_type=self.last_call_metadata["error_type"],
            fallback_available=self.last_call_metadata["fallback_available"],
            fallback_error_type=self.last_call_metadata["fallback_error_type"],
            latency_ms=self.last_call_metadata["latency_ms"],
        )
        if fallback_client is None:
            exc = RuntimeError("%s 请求失败，且未配置可选 fallback" % self.config.provider)
            setattr(exc, "llm_metadata", dict(self.last_call_metadata))
            raise exc from error
        exc = RuntimeError("%s 与 %s 请求均失败" % (self.config.provider, fallback_provider))
        setattr(exc, "llm_metadata", dict(self.last_call_metadata))
        raise exc from error

    def _fallback_target(self) -> Tuple[Optional[OpenAI], str, str]:
        """返回可选 fallback 客户端、Provider 与模型。"""
        if self.config.provider == DEEPSEEK_PROVIDER:
            return self._openrouter_client, "openrouter", self.config.openrouter_model
        return self._deepseek_client, DEEPSEEK_PROVIDER, self.config.deepseek_model

    def _request_provider(
        self,
        client: OpenAI,
        provider: str,
        model: str,
        response_format: Optional[Dict[str, str]],
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        include_openrouter_routing: bool,
        max_retries: Optional[int] = None,
    ) -> Tuple[Optional[str], Dict[str, Any], Optional[Exception]]:
        """调用一个 Provider；返回内容、审计元数据和最后一个异常。"""
        started = time.monotonic()
        retries = 0
        last_exc: Optional[Exception] = None
        retry_limit = self.config.max_retries if max_retries is None else max_retries
        for attempt in range(retry_limit + 1):
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
                if include_openrouter_routing and self.config.fallback_models:
                    # OpenRouter 的 OpenAI-compatible 接口通过 extra_body 接收
                    # 有序候选模型；DeepSeek 不接受该 OpenRouter 专用参数。
                    kwargs["extra_body"] = {"models": list(self.config.fallback_models)}
                response = client.chat.completions.create(**kwargs)
                content = response.choices[0].message.content if response.choices else None
                if not content:
                    raise RuntimeError("empty_response")
                usage = getattr(response, "usage", None)
                metadata = {
                    "provider": provider,
                    "model": model,
                    "retry_count": retries,
                    "status": "success",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "input_tokens": getattr(usage, "prompt_tokens", None),
                    "output_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                    "fallback_models": list(self.config.fallback_models) if include_openrouter_routing else [],
                }
                log_event(
                    "llm_provider_request",
                    provider=provider,
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
                    provider=provider,
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
                if attempt < retry_limit:
                    retries += 1
                    time.sleep(min(0.25 * (2 ** attempt), 1.0))
        return None, {
            "provider": provider,
            "model": model,
            "retry_count": retries,
            "status": "error",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error_type": type(last_exc).__name__ if last_exc else "unknown",
            "error_category": _error_category(last_exc) if last_exc else "unknown",
            "fallback_models": list(self.config.fallback_models) if include_openrouter_routing else [],
        }, last_exc

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        return self._request({"type": "json_object"}, system_prompt, user_prompt, 0, self.config.max_tokens)

    def complete_text(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        return self._request(None, system_prompt, user_prompt, 0.2, max_tokens or self.config.max_tokens).strip()


def _parse_model_list(raw: str) -> Tuple[str, ...]:
    """解析逗号分隔的 OpenRouter 候选模型，去重并保持配置顺序。"""
    models = []
    for item in raw.split(","):
        model = item.strip()
        if model and model not in models:
            models.append(model)
    return tuple(models)


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


def provider_status(root: Path) -> Dict[str, Any]:
    """返回不含密钥的 Provider 运行状态，供治理后台使用。"""
    load_env_file(root / ".env")
    provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    if provider == "deepseek":
        primary_key = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
        model = os.getenv("LLM_MODEL", "").strip()
        if model in {"", LEGACY_OPENROUTER_MODEL}:
            model = os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip()
        fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", "openrouter").strip().lower() or "openrouter"
        fallback_configured = bool(os.getenv("OPENROUTER_API_KEY", "").strip()) if fallback_provider == "openrouter" else False
    else:
        primary_key = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
        model = os.getenv("LLM_MODEL", "").strip() or os.getenv("OPENROUTER_MODEL", LEGACY_OPENROUTER_MODEL).strip()
        fallback_provider = "deepseek"
        fallback_configured = bool(os.getenv("DEEPSEEK_API_KEY", "").strip())
    return {
        "primary_provider": provider,
        "model": model or (DEFAULT_MODEL if provider == "deepseek" else LEGACY_OPENROUTER_MODEL),
        "status": "available" if primary_key else "not_configured",
        "fallback_provider": fallback_provider if fallback_configured else "disabled",
        "fallback_configured": fallback_configured,
    }
