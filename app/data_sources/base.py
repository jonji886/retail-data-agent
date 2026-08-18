"""数据源抽象接口。

让 Agent / Skill 不直接绑定 DuckDB 连接细节。
当前只实现 DuckDBDataSource；PostgreSQL / MySQL / Warehouse 是未来扩展方向。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


class DataSourceBase(ABC):
    """数据源抽象接口。"""

    @abstractmethod
    def execute_readonly(self, sql: str) -> List[Dict[str, Any]]:
        """执行只读查询，返回行列表。"""

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """返回数据源元信息（表列表、行数等）。"""

    @abstractmethod
    def get_date_range(self, table: str = "fact_sales_daily", date_column: str = "sale_date") -> Tuple[Optional[date], Optional[date]]:
        """返回指定表的日期范围。"""

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查。"""
