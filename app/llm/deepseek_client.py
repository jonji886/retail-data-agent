"""DeepSeek OpenAI-compatible API 客户端。"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI


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
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    timeout_seconds: float = 60.0
    max_tokens: int = 1200

    @classmethod
    def from_env(cls, root: Path) -> "DeepSeekConfig":
        load_env_file(root / ".env")
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("未找到 DEEPSEEK_API_KEY，请在项目 .env 中配置")
        return cls(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
            timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
            max_tokens=int(os.getenv("DEEPSEEK_MAX_TOKENS", "1200")),
        )


class DeepSeekClient:
    def __init__(self, config: DeepSeekConfig) -> None:
        self.config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout_seconds,
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
            raise RuntimeError("DeepSeek 返回了空内容")
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
            raise RuntimeError("DeepSeek 返回了空内容")
        return content.strip()
