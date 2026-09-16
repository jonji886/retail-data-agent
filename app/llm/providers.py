"""Model Provider 注册表：集中维护各 Provider 的网关、密钥与默认模型。

设计边界：

* Provider 只描述“怎么连上网关、用哪个 Key、默认模型是什么”，不承载业务语义；
* Agent / Skill / 语义层 / SQL 执行只依赖统一的 LLMClient 接口，不直接依赖任何
  具体模型 SDK。所有 Provider 均通过 OpenAI-compatible Chat Completions 接入，
  因此无需为新增模型引入额外 SDK；
* 新增 Provider 只需要在这里登记一条 ProviderSpec，并通过 ``LLM_PROVIDER``
  环境变量选择，不改动任何业务代码。

模型角色（Router / Main / Reason / Vision）的具体模型名仍由环境变量提供；
Provider 前缀变量（如 ``QWEN_MAIN_MODEL``）允许在不影响默认 Provider 的前提下为
某个 Provider 单独配置角色模型，主要服务于多模型 Benchmark 对比。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

DEFAULT_PROVIDER_NAME = "deepseek"


@dataclass(frozen=True)
class ProviderSpec:
    """一个 OpenAI-compatible Model Provider 的静态描述。"""

    name: str
    display_name: str
    api_key_envs: Tuple[str, ...]
    default_base_url: str
    base_url_envs: Tuple[str, ...] = ()
    default_main_model: str = ""
    # 角色模型前缀变量：DEEPSEEK_MAIN_MODEL / QWEN_MAIN_MODEL 等
    model_env_prefix: str = ""
    # 角色 → 默认模型（可选）；未提供时角色模型必须显式配置
    role_default_models: Dict[str, str] = field(default_factory=dict)

    def resolve_api_key(self) -> Tuple[str, str]:
        """返回 (api_key, 命中的环境变量名)；未配置时返回 ("", "")。"""
        for name in self.api_key_envs:
            value = os.getenv(name, "").strip()
            if value:
                return value, name
        return "", ""

    def resolve_base_url(self) -> str:
        for name in self.base_url_envs:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return self.default_base_url

    def role_model_override(self, role: str) -> str:
        """读取标准 <PREFIX>_<ROLE>_MODEL，兼容旧的角色变量命名。"""
        if not self.model_env_prefix:
            return ""
        role_names = {
            "router": ("ROUTER",),
            "main": ("MAIN",),
            "reason": ("REASONING", "REASON"),
            "vision": ("VISION",),
        }.get(role, (role.upper(),))
        names = tuple("%s_%s_MODEL" % (self.model_env_prefix, item) for item in role_names) + tuple(
            "%s_%s" % (self.model_env_prefix, item) for item in role_names
        )
        for name in names:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return ""

    def role_model(self, role: str) -> str:
        """读取 Provider 专属模型配置；Main 可使用通用 LLM_MODEL 覆盖。"""
        legacy_roles = {
            "router": ("ROUTER", "MODEL_ROUTER"),
            "main": ("MAIN", "MODEL_MAIN", "MODEL_DEEPSEEK"),
            "reason": ("REASON", "MODEL_REASON", "MODEL_QWEN", "MODEL_GLM"),
            "vision": ("VISION", "MODEL_VISION"),
        }
        if role == "main":
            configured = (
                self.role_model_override(role)
                or os.getenv("LLM_MAIN_MODEL", "").strip()
                or os.getenv("LLM_MODEL", "").strip()
            )
        else:
            configured = self.role_model_override(role)
            generic_names = {
                "router": ("LLM_ROUTER_MODEL",),
                "reason": ("LLM_REASONING_MODEL", "LLM_REASON_MODEL"),
                "vision": ("LLM_VISION_MODEL",),
            }.get(role, ())
            for name in generic_names:
                configured = configured or os.getenv(name, "").strip()
        if configured:
            return configured
        if self.name == "siliconflow":
            for name in legacy_roles.get(role, ()):
                value = os.getenv(name, "").strip()
                if value:
                    return value
        return self.role_default_models.get(role, "")


PROVIDER_REGISTRY: Dict[str, ProviderSpec] = {
    "deepseek": ProviderSpec(
        name="deepseek",
        display_name="DeepSeek API",
        api_key_envs=("DEEPSEEK_API_KEY",),
        default_base_url="https://api.deepseek.com",
        base_url_envs=("DEEPSEEK_BASE_URL",),
        default_main_model="deepseek-flash",
        model_env_prefix="DEEPSEEK",
        role_default_models={"main": "deepseek-v4-flash"},
    ),
    "siliconflow": ProviderSpec(
        name="siliconflow",
        display_name="硅基流动",
        api_key_envs=("SILICONFLOW_API_KEY",),
        default_base_url="https://api.siliconflow.cn/v1",
        base_url_envs=("SILICONFLOW_BASE_URL", "LLM_BASE_URL"),
        default_main_model="deepseek-ai/DeepSeek-V4-Flash",
        model_env_prefix="SILICONFLOW",
    ),
    "qwen": ProviderSpec(
        name="qwen",
        display_name="通义千问（阿里云百炼）",
        api_key_envs=("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        base_url_envs=("QWEN_BASE_URL", "LLM_BASE_URL"),
        default_main_model="qwen3.8-flash",
        model_env_prefix="QWEN",
        role_default_models={"main": "qwen3.8-flash"},
    ),
}


def resolve_provider(name: Optional[str] = None) -> ProviderSpec:
    """按名称解析 Provider；名称为空时使用 LLM_PROVIDER 环境变量。"""
    raw = (name if name is not None else os.getenv("LLM_PROVIDER", "")).strip()
    key = (raw or DEFAULT_PROVIDER_NAME).lower()
    spec = PROVIDER_REGISTRY.get(key)
    if spec is None:
        raise RuntimeError(
            "未知 LLM_PROVIDER=%s；当前支持：%s。"
            % (raw or key, "/".join(sorted(PROVIDER_REGISTRY)))
        )
    return spec


def available_providers() -> Tuple[str, ...]:
    return tuple(PROVIDER_REGISTRY)
