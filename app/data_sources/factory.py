"""根据 Settings 创建业务使用的数据源。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from app.config import DataSourceConfig
from app.data_sources.base import DataSourceBase
from app.data_sources.duckdb import DuckDBDataSource
from app.data_sources.postgresql import PostgreSQLDataSource


def create_data_source(root: Path, config: Optional[DataSourceConfig] = None) -> DataSourceBase:
    selected = config or DataSourceConfig.from_env(root)
    if selected.kind == "duckdb":
        return DuckDBDataSource(selected.duckdb_path)
    max_rows = int(os.getenv("DB_MAX_RESULT_ROWS", "1000"))
    if max_rows <= 0:
        raise RuntimeError("DB_MAX_RESULT_ROWS 必须大于 0")
    return PostgreSQLDataSource(
        selected.database_url,
        pool_size=selected.pool_size,
        connect_timeout=selected.connect_timeout,
        statement_timeout_ms=selected.statement_timeout_ms,
        max_result_rows=max_rows,
    )
