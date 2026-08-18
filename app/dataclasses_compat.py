"""dataclasses 兼容工具，便于把 frozen dataclass 转成 dict。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def asdict_safe(obj: Any) -> Any:
    """安全地把 dataclass 转 dict；非 dataclass 原样返回。"""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj
