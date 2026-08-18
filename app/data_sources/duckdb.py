"""DuckDB 数据源实现。

复用 ReadOnlySQLRunner 的安全校验，作为 Agent 访问 DuckDB 的统一适配层。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from app.data_sources.base import DataSourceBase
from app.tools.sql_runner import ReadOnlySQLRunner, SQLSafetyError


class DuckDBDataSource(DataSourceBase):
    """DuckDB 只读数据源。"""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._runner = ReadOnlySQLRunner(database_path)

    def execute_readonly(self, sql: str) -> List[Dict[str, Any]]:
        """执行只读查询（经过 SQL 安全校验）。"""
        return self._runner.query(sql)

    def get_metadata(self) -> Dict[str, Any]:
        """返回表列表与行数。"""
        tables = [
            "dim_date", "dim_region", "dim_store", "dim_product", "dim_channel",
            "fact_sales_daily", "fact_inventory_daily", "fact_traffic_daily",
            "v_sales_enriched", "v_inventory_enriched", "v_traffic_enriched",
        ]
        meta: Dict[str, Any] = {"tables": {}}
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            for table in tables:
                try:
                    count = connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                    meta["tables"][table] = {"row_count": count}
                except Exception:  # noqa: BLE001
                    meta["tables"][table] = {"row_count": None, "error": "table not found"}
        finally:
            connection.close()
        return meta

    def get_date_range(self, table: str = "fact_sales_daily", date_column: str = "sale_date") -> Tuple[Optional[date], Optional[date]]:
        """返回指定表的日期范围。"""
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            row = connection.execute(
                "SELECT MIN(%s), MAX(%s) FROM %s" % (date_column, date_column, table)
            ).fetchone()
        except Exception:  # noqa: BLE001
            return None, None
        finally:
            connection.close()
        if not row or not row[0]:
            return None, None
        return row[0], row[1]

    def health_check(self) -> bool:
        """健康检查：能否成功查询。"""
        try:
            self._runner.query("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False
