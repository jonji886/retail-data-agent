"""只读 SQL 执行器，作为 Agent 访问 DuckDB 的安全边界。

安全策略集中在本模块，避免不同数据访问路径各自配置一套 DuckDB 连接。
应用层 SQL guard 与 DuckDB capability lockdown 同时生效：前者拦截明显的
管理/写操作，后者阻止 SELECT 形式的外部文件、HTTP 与扩展访问。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb


class SQLSafetyError(ValueError):
    """SQL 不符合只读查询约束或触发了数据库安全策略。"""

    def __init__(self, message: str, reason_code: str = "query_rejected",
                 guard_stage: str = "sql_guard") -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.guard_stage = guard_stage


class SQLResourceLimitError(SQLSafetyError):
    """查询结果超过受控资源上限。"""


@dataclass(frozen=True)
class SQLExecutionPolicy:
    """DuckDB 只读执行的资源与能力策略。"""

    max_result_rows: int = 1000
    memory_limit: str = "512MB"
    threads: int = 2

    @classmethod
    def from_env(cls) -> "SQLExecutionPolicy":
        """读取非安全开关类资源参数；外部访问始终保持 deny-by-default。"""
        return cls(
            max_result_rows=_positive_int_from_env("DB_MAX_RESULT_ROWS", 1000),
            memory_limit=os.getenv("DB_MEMORY_LIMIT", "512MB").strip() or "512MB",
            threads=_positive_int_from_env("DB_THREADS", 2),
        )


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|copy|attach|detach|pragma|install|load)\b",
    re.IGNORECASE,
)


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def open_readonly_connection(database_path: Path,
                             policy: Optional[SQLExecutionPolicy] = None) -> duckdb.DuckDBPyConnection:
    """创建锁定能力的 DuckDB 只读连接。

    ``enable_external_access=false`` 是关键安全边界；其余配置关闭扩展自动
    加载/安装、限制资源，并在连接创建时锁定，防止后续 SQL 重新打开配置。
    """
    selected = policy or SQLExecutionPolicy.from_env()
    connection = duckdb.connect(
        str(database_path),
        read_only=True,
        config={
            "enable_external_access": "false",
            "allow_community_extensions": "false",
            "allow_unsigned_extensions": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
            "enable_external_file_cache": "false",
            "memory_limit": selected.memory_limit,
            "threads": str(selected.threads),
            "lock_configuration": "true",
        },
    )
    return connection


class ReadOnlySQLRunner:
    def __init__(self, database_path: Path,
                 policy: Optional[SQLExecutionPolicy] = None) -> None:
        self.database_path = database_path
        self.policy = policy or SQLExecutionPolicy.from_env()

    @staticmethod
    def validate(sql: str) -> str:
        normalized = sql.strip()
        if normalized.endswith(";"):
            normalized = normalized[:-1].rstrip()
        if not normalized:
            raise SQLSafetyError("SQL 不能为空", "empty_query")
        if ";" in normalized:
            raise SQLSafetyError(
                "只允许执行一条 SQL", "multiple_statements_not_allowed"
            )
        if not re.match(r"^select\b", normalized, re.IGNORECASE):
            raise SQLSafetyError("只允许执行 SELECT 查询", "non_select_not_allowed")
        if _FORBIDDEN.search(normalized):
            raise SQLSafetyError(
                "SQL 包含被禁止的写操作或管理操作", "mutation_not_allowed"
            )
        return normalized

    def query(self, sql: str) -> List[Dict[str, Any]]:
        safe_sql = self.validate(sql)
        connection = open_readonly_connection(self.database_path, self.policy)
        try:
            try:
                cursor = connection.execute(safe_sql)
                rows = cursor.fetchmany(self.policy.max_result_rows + 1)
            except Exception as exc:  # noqa: BLE001
                if _is_external_access_error(exc):
                    raise SQLSafetyError(
                        "查询访问了被禁止的外部资源",
                        "external_access_blocked",
                        "duckdb_capability_lockdown",
                    ) from None
                raise SQLSafetyError(
                    "SQL 查询执行失败",
                    "query_execution_failed",
                    "duckdb_execution",
                ) from None

            if len(rows) > self.policy.max_result_rows:
                raise SQLResourceLimitError(
                    "查询结果超过最大返回行数限制",
                    "result_limit_exceeded",
                    "result_guard",
                )
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            connection.close()


def _is_external_access_error(exc: Exception) -> bool:
    """识别 DuckDB capability lockdown 的错误，不把内部细节暴露给用户。"""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "file system operations are disabled",
            "cannot access file",
            "cannot access directory",
            "external access",
        )
    )
