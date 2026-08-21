"""OpenRouter OpenAI-compatible API 客户端。"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openai import OpenAI


DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"
DEFAULT_PROVIDER = "openrouter"


def load_env_file(path: Path) -> None:
    """加载简单 .env 文件；不覆盖已经存在的进程环境变量。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        try:
            value = shlex.split(raw_value, comments=True)[0] if raw_value.strip() else ""
        except ValueError:
            value = raw_value.strip().strip("\"'")
        os.environ[key] = value


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 60.0
    max_tokens: int = 1200
    http_referer: str = ""
    app_title: str = "Retail Data Agent"

    @classmethod
    def from_env(cls, root: Path) -> "OpenRouterConfig":
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        if provider != DEFAULT_PROVIDER:
            raise RuntimeError("LLM_PROVIDER=%s 暂不支持，当前运行链路需要设置为 openrouter" % provider)

        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未找到 OPENROUTER_API_KEY，请在本地 .env 或 Render Environment 中配置")
        base_url = os.getenv("OPENROUTER_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
        model = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        try:
            timeout_seconds = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60"))
            max_tokens = int(os.getenv("OPENROUTER_MAX_TOKENS", "1200"))
        except ValueError as exc:
            raise RuntimeError(
                "OPENROUTER_TIMEOUT_SECONDS 必须是数字，OPENROUTER_MAX_TOKENS 必须是整数"
            ) from exc
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise RuntimeError("OPENROUTER_TIMEOUT_SECONDS 和 OPENROUTER_MAX_TOKENS 必须大于 0")
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            http_referer=os.getenv("OPENROUTER_HTTP_REFERER", "").strip(),
            app_title=os.getenv("OPENROUTER_APP_TITLE", "Retail Data Agent").strip() or "Retail Data Agent",
        )

    @classmethod
    def is_configured(cls, root: Path) -> bool:
        """判断当前进程是否已提供 OpenRouter 配置，不暴露 Key。"""
        load_env_file(root / ".env")
        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
        return provider == DEFAULT_PROVIDER and bool(os.getenv("OPENROUTER_API_KEY", "").strip())


class OpenRouterClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config
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

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=self.config.max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenRouter 返回了空内容")
        return content

    def complete_text(self, system_prompt: str, user_prompt: str, max_tokens: Optional[int] = None) -> str:
        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=max_tokens or self.config.max_tokens,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("OpenRouter 返回了空内容")
        return content.strip()
