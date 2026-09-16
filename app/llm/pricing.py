"""模型 Token 用量估算与集中价格表读取。"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICING_PATH = PROJECT_ROOT / "configs" / "models" / "model_pricing.json"


@lru_cache(maxsize=8)
def _load_pricing(path: str) -> Dict[str, Any]:
    pricing_path = Path(path)
    if not pricing_path.exists():
        return {}
    return json.loads(pricing_path.read_text(encoding="utf-8"))


def pricing_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """加载价格配置；路径作为缓存键，便于单测使用临时配置。"""
    return _load_pricing(str(path or DEFAULT_PRICING_PATH))


def estimate_tokens(text: str) -> int:
    """无 Provider Usage 时的粗略估算：CJK 字符按 1，其余字符每 4 个按 1。"""
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other_chars = len(text) - cjk_chars
    return max(1, cjk_chars + math.ceil(other_chars / 4)) if text else 0


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    pricing_path: Optional[Path] = None,
) -> Optional[float]:
    """依据集中价格表计算 Provider 计价币种的估算成本；缺项时返回 None。"""
    if input_tokens is None or output_tokens is None:
        return None
    table = pricing_config(pricing_path)
    model_price = table.get("models", {}).get(provider, {}).get(model)
    if not isinstance(model_price, dict):
        return None
    input_price = model_price.get("input")
    output_price = model_price.get("output")
    if input_price is None or output_price is None:
        return None
    total = (input_tokens * float(input_price) + output_tokens * float(output_price)) / 1_000_000
    return round(total, 9)


def pricing_currency(provider: str, pricing_path: Optional[Path] = None) -> str:
    """返回价格表中配置的 Provider 计价币种。"""
    table = pricing_config(pricing_path)
    return str(table.get("provider_currencies", {}).get(provider, table.get("currency", "")))
