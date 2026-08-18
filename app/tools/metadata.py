"""元数据 Tool：提供数据上下文（数据时间范围、最新数据日期等）。

移除 Prompt 中硬编码的"数据最新日期固定为某一天"，
让"本月""最近一个月"等表达基于 latest_data_date 计算。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb

from app.agent.contracts import ToolResult


class MetadataTool:
    """提供数据集元信息，供 parse_request 与 generate_answer 使用。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def get_data_context(self) -> Dict[str, Any]:
        """返回 {dataset_min_date, dataset_max_date, latest_data_date, timezone, last_refresh_at}。"""
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            row = connection.execute(
                "SELECT MIN(sale_date), MAX(sale_date) FROM fact_sales_daily"
            ).fetchone()
        finally:
            connection.close()
        min_date, max_date = row if row else (None, None)
        latest = str(max_date) if max_date else None
        return {
            "dataset_min_date": str(min_date) if min_date else None,
            "dataset_max_date": str(max_date) if max_date else None,
            "latest_data_date": latest,
            "timezone": "Asia/Shanghai",
            "last_refresh_at": None,  # MVP 不记录刷新时间
        }

    def latest_date(self) -> Optional[date]:
        ctx = self.get_data_context()
        if not ctx["latest_data_date"]:
            return None
        return date.fromisoformat(ctx["latest_data_date"])

    def as_result(self) -> ToolResult:
        return ToolResult(success=True, data=self.get_data_context(), metadata={})
