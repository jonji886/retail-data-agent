"""PostgreSQL 只读数据源实现。

Supabase 在本项目中按标准 PostgreSQL 使用。业务层只依赖
``DataSourceBase``，不会感知 Supabase 这个托管产品名称。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.data_sources.base import (
    DataSourceBase,
    DataSourceError,
    DataSourceTimeoutError,
    DataSourceUnavailableError,
)
from app.tools.sql_runner import ReadOnlySQLRunner, SQLResourceLimitError, SQLSafetyError


class PostgreSQLDataSource(DataSourceBase):
    """带连接池、超时和结果行数限制的 PostgreSQL 数据源。"""

    _TABLES = (
        "dim_date", "dim_region", "dim_store", "dim_product", "dim_channel",
        "fact_sales_daily", "fact_inventory_daily", "fact_traffic_daily",
        "v_sales_enriched", "v_inventory_enriched", "v_traffic_enriched",
    )

    def __init__(
        self,
        database_url: str,
        pool_size: int = 5,
        connect_timeout: float = 5.0,
        statement_timeout_ms: int = 10000,
        max_result_rows: Optional[int] = None,
    ) -> None:
        if not database_url.strip():
            raise ValueError("database_url 不能为空")
        self.database_url = database_url
        self.pool_size = pool_size
        self.connect_timeout = connect_timeout
        self.statement_timeout_ms = statement_timeout_ms
        self.max_result_rows = max_result_rows or 1000
        self._pool = None

    @property
    def dialect(self) -> str:
        return "postgresql"

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - dependency install path
            raise DataSourceUnavailableError(
                "PostgreSQL 驱动未安装，请安装 psycopg[binary,pool]",
                "driver_unavailable",
            ) from exc
        try:
            self._pool = ConnectionPool(
                conninfo=self.database_url,
                min_size=1,
                max_size=self.pool_size,
                kwargs={
                    "connect_timeout": self.connect_timeout,
                    "options": "-c statement_timeout=%d" % self.statement_timeout_ms,
                },
                open=True,
            )
            self._pool.wait(timeout=self.connect_timeout)
        except Exception as exc:  # noqa: BLE001
            self._pool = None
            raise self._convert_error(exc, "database_unavailable") from None
        return self._pool

    @staticmethod
    def _convert_error(exc: Exception, reason_code: str = "query_execution_failed") -> DataSourceError:
        message = str(exc).lower()
        if "timeout" in message or "statement timeout" in message or "canceling statement" in message:
            return DataSourceTimeoutError("PostgreSQL 查询超时", "query_timeout")
        if reason_code == "database_unavailable" or "connect" in message or "connection" in message:
            return DataSourceUnavailableError("PostgreSQL 数据源不可用", "database_unavailable")
        return DataSourceError("PostgreSQL 查询失败", reason_code)

    @staticmethod
    def _driver_sql(sql: str) -> str:
        # 归因/异常/报告的安全模板使用 ? 占位符；psycopg 使用 %s。
        return sql.replace("?", "%s")

    def execute_readonly(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        try:
            safe_sql = ReadOnlySQLRunner.validate(sql)
        except SQLSafetyError:
            raise
        pool = self._get_pool()
        try:
            with pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(self._driver_sql(safe_sql), list(params))
                    rows = cursor.fetchmany(self.max_result_rows + 1)
                    if len(rows) > self.max_result_rows:
                        raise SQLResourceLimitError(
                            "查询结果超过最大返回行数限制", "result_limit_exceeded", "result_guard"
                        )
                    columns = [item.name for item in cursor.description]
                    return [dict(zip(columns, row)) for row in rows]
        except (SQLSafetyError, SQLResourceLimitError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._convert_error(exc) from None

    def get_metadata(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"datasource": "postgresql", "tables": {}}
        for table in self._TABLES:
            try:
                rows = self.execute_readonly("SELECT COUNT(*) AS row_count FROM %s" % table)
                result["tables"][table] = {"row_count": rows[0]["row_count"] if rows else None}
            except Exception:  # noqa: BLE001
                result["tables"][table] = {"row_count": None, "error": "table not found"}
        return result

    def get_date_range(self, table: str = "fact_sales_daily", date_column: str = "sale_date") -> Tuple[Optional[date], Optional[date]]:
        try:
            rows = self.execute_readonly(
                "SELECT MIN(%s) AS min_date, MAX(%s) AS max_date FROM %s" % (date_column, date_column, table)
            )
        except DataSourceError:
            return None, None
        if not rows or not rows[0].get("min_date"):
            return None, None
        return rows[0]["min_date"], rows[0]["max_date"]

    def health_check(self) -> bool:
        try:
            return self.execute_readonly("SELECT 1 AS healthy") == [{"healthy": 1}]
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None
