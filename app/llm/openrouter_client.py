"""OpenRouter OpenAI-compatible API 客户端。"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Tuple
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI

from app.config import load_env_file


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"
DEFAULT_PROVIDER = "openrouter"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_PROVIDER = "deepseek"


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    provider: str = DEFAULT_PROVIDER
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
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

    @classmethod
    def from_env(cls, root: Path, mode: str = "demo") -> "OpenRouterConfig":
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        if provider != DEFAULT_PROVIDER:
            raise RuntimeError("LLM_PROVIDER=%s 暂不支持，当前运行链路需要设置为 openrouter" % provider)

        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未找到 OPENROUTER_API_KEY，请在本地 .env 或 Render Environment 中配置")
        base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        if mode not in {"demo", "evaluation"}:
            raise RuntimeError("LLM 配置 mode 仅支持 demo 或 evaluation")
        configured_model = os.getenv("LLM_MODEL", "").strip() or os.getenv("OPENROUTER_MODEL", "").strip()
        if mode == "evaluation":
            model = os.getenv("EVAL_LLM_MODEL", "").strip()
            if not model:
                raise RuntimeError("真实 Evaluation 必须配置固定的 EVAL_LLM_MODEL")
            if model == DEFAULT_MODEL or model.endswith("/free"):
                raise RuntimeError("EVAL_LLM_MODEL 必须是固定的具体模型，不能使用 openrouter/free")
        else:
            model = configured_model or DEFAULT_MODEL
        try:
            timeout_seconds = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60"))
            max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "1200"))
            max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        except ValueError as exc:
            raise RuntimeError(
                "OPENROUTER_TIMEOUT_SECONDS 必须是数字，OPENROUTER_MAX_TOKENS 必须是整数"
            ) from exc
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise RuntimeError("OPENROUTER_TIMEOUT_SECONDS 和 OPENROUTER_MAX_TOKENS 必须大于 0")
        if max_retries < 0 or max_retries > 2:
            raise RuntimeError("LLM_MAX_RETRIES 必须在 0 到 2 之间")
        fallback_models = _parse_model_list(os.getenv("OPENROUTER_FALLBACK_MODELS", ""))
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            max_retries=max_retries,
            fallback_model=os.getenv("LLM_FALLBACK_MODEL", "deterministic").strip() or "deterministic",
            fallback_models=fallback_models,
            http_referer=os.getenv("OPENROUTER_HTTP_REFERER", "").strip(),
            app_title=os.getenv("OPENROUTER_APP_TITLE", "Retail Data Agent").strip() or "Retail Data Agent",
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL,
            deepseek_model=os.getenv("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL,
        )

    @classmethod
    def is_configured(cls, root: Path, mode: str = "demo") -> bool:
        """判断当前进程是否已提供 OpenRouter 配置，不暴露 Key。"""
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        if provider != DEFAULT_PROVIDER or not os.getenv("OPENROUTER_API_KEY", "").strip():
            return False
        if mode == "evaluation":
            model = os.getenv("EVAL_LLM_MODEL", "").strip()
            return bool(model) and model != DEFAULT_MODEL and not model.endswith("/free")
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
        if config.deepseek_api_key:
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
            return content

        # OpenRouter 已按 max_retries 重试仍失败时，才跨 Provider 切换。
        # DeepSeek fallback 不会再叠加 OpenRouter 的候选模型路由参数。
        fallback_error: Optional[Exception] = None
        if self._deepseek_client is not None:
            fallback_content, fallback_metadata, fallback_error = self._request_provider(
                self._deepseek_client, DEEPSEEK_PROVIDER, self.config.deepseek_model,
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
                    "fallback_reason": type(error).__name__ if error else "provider_error",
                    "primary_retry_count": metadata.get("retry_count", 0),
                }
                return fallback_content
            error = fallback_error or error

        self.last_call_metadata = {
            **metadata,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "status": "error",
            "error_type": type(error).__name__ if error else "unknown",
            "fallback_available": self._deepseek_client is not None,
            "fallback_attempted": self._deepseek_client is not None,
            "fallback_provider": DEEPSEEK_PROVIDER if self._deepseek_client is not None else None,
            "fallback_error_type": type(fallback_error).__name__ if fallback_error else None,
        }
        raise RuntimeError("OpenRouter 与 DeepSeek 请求均失败") from error

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
                return content, {
                    "provider": provider,
                    "model": model,
                    "retry_count": retries,
                    "status": "success",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "input_tokens": getattr(usage, "prompt_tokens", None),
                    "output_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                    "fallback_models": list(self.config.fallback_models) if include_openrouter_routing else [],
                }, None
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
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
