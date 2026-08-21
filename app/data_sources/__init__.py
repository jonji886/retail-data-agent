"""数据源抽象与实现。"""

from app.data_sources.base import DataSourceBase
from app.data_sources.duckdb import DuckDBDataSource
from app.data_sources.factory import create_data_source
from app.data_sources.postgresql import PostgreSQLDataSource

__all__ = ["DataSourceBase", "DuckDBDataSource", "PostgreSQLDataSource", "create_data_source"]
