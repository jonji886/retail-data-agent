"""销售变化的确定性贡献度拆解。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.tools.sql_runner import open_readonly_connection


@dataclass(frozen=True)
class Contribution:
    dimension: str
    member: str
    current_value: float
    comparison_value: float
    delta: float
    contribution_rate: Optional[float]


@dataclass(frozen=True)
class AttributionResult:
    scope: str
    current_period: str
    comparison_period: str
    current_total: float
    comparison_total: float
    total_delta: float
    dimension: str
    contributions: List[Contribution]

    @property
    def top_negative(self) -> List[Contribution]:
        return sorted((item for item in self.contributions if item.delta < 0), key=lambda item: item.delta)[:5]


_DIMENSIONS = {
    "city_name": "城市",
    "store_name": "门店",
    "category_name": "品类",
    "brand_name": "品牌",
    "channel_name": "渠道",
}


def _month_range(month: str) -> Tuple[date, date]:
    year, month_number = [int(part) for part in month.split("-")]
    start = date(year, month_number, 1)
    end = date(year, month_number + 1, 1) - timedelta(days=1) if month_number < 12 else date(year, 12, 31)
    return start, end


def _previous_month(month: str) -> str:
    year, month_number = [int(part) for part in month.split("-")]
    index = year * 12 + month_number - 2
    previous_year, previous_index = divmod(index, 12)
    return "%04d-%02d" % (previous_year, previous_index + 1)


class SalesAttributor:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def analyze(
        self,
        month: str,
        dimension: str = "store_name",
        region_name: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> AttributionResult:
        if dimension not in _DIMENSIONS:
            raise ValueError("暂不支持的归因维度：%s" % dimension)
        current_start, current_end = _month_range(month)
        previous_month = _previous_month(month)
        previous_start, previous_end = _month_range(previous_month)
        # 权限范围在 SQL 层过滤，避免越权查看全量数据。
        scope_clauses: List[str] = []
        scope_params: List[str] = []
        if region_name:
            scope_clauses.append("region_name = ?")
            scope_params.append(region_name)
        if store_id:
            scope_clauses.append("store_id = ?")
            scope_params.append(store_id)
        scope_sql = (" AND " + " AND ".join(scope_clauses)) if scope_clauses else ""
        params: List[str] = (
            [current_start.isoformat(), current_end.isoformat()]
            + scope_params
            + [previous_start.isoformat(), previous_end.isoformat()]
            + scope_params
        )
        query = (
            "SELECT period, member, SUM(sales_amount) AS sales_amount FROM ("
            "SELECT 'current' AS period, %s AS member, sales_amount FROM v_sales_enriched "
            "WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s "
            "UNION ALL "
            "SELECT 'comparison' AS period, %s AS member, sales_amount FROM v_sales_enriched "
            "WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s"
            ") GROUP BY 1, 2 ORDER BY 1, 2"
            % (dimension, scope_sql, dimension, scope_sql)
        )
        connection = open_readonly_connection(self.database_path)
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()

        current: Dict[str, float] = {}
        comparison: Dict[str, float] = {}
        for period, member, value in rows:
            target = current if period == "current" else comparison
            target[str(member)] = float(value)
        members = sorted(set(current) | set(comparison))
        current_total = sum(current.values())
        comparison_total = sum(comparison.values())
        total_delta = current_total - comparison_total
        contributions = [
            Contribution(
                dimension=dimension,
                member=member,
                current_value=current.get(member, 0.0),
                comparison_value=comparison.get(member, 0.0),
                delta=current.get(member, 0.0) - comparison.get(member, 0.0),
                contribution_rate=(current.get(member, 0.0) - comparison.get(member, 0.0)) / total_delta if total_delta else None,
            )
            for member in members
        ]
        return AttributionResult(
            scope=region_name or store_id or "全部区域",
            current_period=month,
            comparison_period=previous_month,
            current_total=current_total,
            comparison_total=comparison_total,
            total_delta=total_delta,
            dimension=dimension,
            contributions=contributions,
        )
