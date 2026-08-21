"""数据源抽象接口与统一错误类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple


class DataSourceError(RuntimeError):
    """数据源错误，不把底层驱动异常直接暴露给用户。"""

    def __init__(self, message: str, reason_code: str = "data_source_error") -> None:
        super().__init__(message)
        self.reason_code = reason_code


class DataSourceUnavailableError(DataSourceError):
    """数据源无法连接或不可用。"""


class DataSourceTimeoutError(DataSourceError):
    """数据源连接或查询超时。"""


class DataSourceBase(ABC):
    """数据源抽象接口。"""

    @abstractmethod
    def execute_readonly(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        """执行只读查询，返回行列表。``params`` 使用驱动参数化语法。"""

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """返回数据源元信息（表列表、行数等）。"""

    @abstractmethod
    def get_date_range(self, table: str = "fact_sales_daily", date_column: str = "sale_date") -> Tuple[Optional[date], Optional[date]]:
        """返回指定表的日期范围。"""

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查。"""

    @property
    def dialect(self) -> str:
        """SQL 方言名称，仅用于数据源适配层的表达差异。"""
        return "generic"

    def close(self) -> None:
        """释放连接池资源；不需要资源的数据源无需实现。"""
