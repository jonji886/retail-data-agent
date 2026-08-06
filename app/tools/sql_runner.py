"""只读 SQL 执行器，作为 Agent 访问 DuckDB 的安全边界。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import duckdb


class SQLSafetyError(ValueError):
    """SQL 不符合只读查询约束。"""


_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|copy|attach|detach|pragma|install|load)\b", re.IGNORECASE)


class ReadOnlySQLRunner:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    @staticmethod
    def validate(sql: str) -> str:
        normalized = sql.strip().rstrip(";").strip()
        if not normalized:
            raise SQLSafetyError("SQL 不能为空")
        if ";" in normalized:
            raise SQLSafetyError("只允许执行一条 SQL")
        if not re.match(r"^select\b", normalized, re.IGNORECASE):
            raise SQLSafetyError("只允许执行 SELECT 查询")
        if _FORBIDDEN.search(normalized):
            raise SQLSafetyError("SQL 包含被禁止的写操作或管理操作")
        return normalized

    def query(self, sql: str) -> List[Dict[str, Any]]:
        safe_sql = self.validate(sql)
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            cursor = connection.execute(safe_sql)
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            connection.close()

