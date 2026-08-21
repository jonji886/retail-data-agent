"""确定性经营异常检测。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.data_sources.base import DataSourceBase
from app.data_sources.duckdb import DuckDBDataSource


@dataclass(frozen=True)
class Anomaly:
    metric: str
    entity_level: str
    entity_id: str
    entity_name: str
    period: str
    current_value: float
    baseline_value: float
    change_rate: float
    severity: str
    rule: str


_LEVELS = {
    "region": ("region_id", "region_name"),
    "store": ("store_id", "store_name"),
    "category": ("category_name", "category_name"),
}


def _month_range(month: str) -> Tuple[date, date]:
    year, month_number = [int(part) for part in month.split("-")]
    start = date(year, month_number, 1)
    if month_number == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month_number + 1, 1) - timedelta(days=1)
    return start, end


def _previous_month(month: str, offset: int) -> str:
    year, month_number = [int(part) for part in month.split("-")]
    index = year * 12 + month_number - 1 - offset
    previous_year, previous_index = divmod(index, 12)
    return "%04d-%02d" % (previous_year, previous_index + 1)


class SalesAnomalyDetector:
    def __init__(self, database_path: Optional[Path] = None,
                 data_source: Optional[DataSourceBase] = None) -> None:
        self.data_source = data_source or DuckDBDataSource(database_path or Path("data/retail.duckdb"))

    def detect(
        self,
        month: str,
        entity_level: str = "region",
        threshold: float = -0.15,
        baseline_months: int = 3,
        region_name: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> List[Anomaly]:
        if entity_level not in _LEVELS:
            raise ValueError("暂不支持的预警对象：%s" % entity_level)
        if not -1 < threshold < 0:
            raise ValueError("销售下降阈值必须在 -1 和 0 之间")
        if baseline_months < 1 or baseline_months > 12:
            raise ValueError("基线月份数必须在 1 和 12 之间")
        current_start, current_end = _month_range(month)
        baseline_start, _ = _month_range(_previous_month(month, baseline_months))
        previous_month = _previous_month(month, 1)
        _, baseline_end = _month_range(previous_month)
        id_column, name_column = _LEVELS[entity_level]
        # 权限范围在 SQL 层过滤，避免门店经理/区域经理看到越权数据。
        scope_sql = ""
        scope_params: List[str] = []
        if region_name:
            scope_sql += " AND region_name = ?"
            scope_params.append(region_name)
        if store_id:
            scope_sql += " AND store_id = ?"
            scope_params.append(store_id)
        rows_dict = self.data_source.execute_readonly(
            """
                SELECT date_trunc('month', sale_date) AS month_start,
                       %s AS entity_id,
                       %s AS entity_name,
                       SUM(sales_amount) AS sales_amount
                FROM v_sales_enriched
                WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s
                GROUP BY 1, 2, 3
                ORDER BY 1, 2
                """ % (id_column, name_column, scope_sql),
            [baseline_start.isoformat(), current_end.isoformat()] + scope_params,
        )
        rows = [tuple(row.values()) for row in rows_dict]

        current_values: Dict[str, Tuple[str, float]] = {}
        baseline_values: Dict[str, List[float]] = {}
        for month_start, entity_id, entity_name, value in rows:
            month_value = month_start.strftime("%Y-%m")
            if month_value == month:
                current_values[str(entity_id)] = (str(entity_name), float(value))
            elif baseline_start.strftime("%Y-%m") <= month_value <= previous_month:
                baseline_values.setdefault(str(entity_id), []).append(float(value))

        anomalies: List[Anomaly] = []
        for entity_id, (entity_name, current_value) in current_values.items():
            values = baseline_values.get(entity_id, [])
            if not values:
                continue
            baseline_value = sum(values) / len(values)
            change_rate = (current_value - baseline_value) / baseline_value if baseline_value else 0.0
            if change_rate > threshold:
                continue
            severity = "critical" if change_rate <= -0.30 else "high" if change_rate <= -0.20 else "medium"
            anomalies.append(
                Anomaly(
                    metric="sales_amount",
                    entity_level=entity_level,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    period=month,
                    current_value=current_value,
                    baseline_value=baseline_value,
                    change_rate=change_rate,
                    severity=severity,
                    rule="较前 %d 个月平均销售额下降超过 %.0f%%" % (baseline_months, abs(threshold) * 100),
                )
            )
        return sorted(anomalies, key=lambda item: item.change_rate)
