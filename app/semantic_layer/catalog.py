"""指标语义层：读取配置并生成受约束的聚合 SQL。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _sql_literal(value: str) -> str:
    return "'%s'" % value.replace("'", "''")


class SemanticLayerError(ValueError):
    """语义层配置或查询参数不合法。"""


@dataclass(frozen=True)
class Metric:
    name: str
    display_name: str
    description: str
    source_table: str
    expression: str
    dimensions: List[str]
    time_grains: List[str]
    synonyms: List[str]
    format: str


class MetricCatalog:
    def __init__(self, metrics: Mapping[str, Metric]) -> None:
        self._metrics = dict(metrics)

    @classmethod
    def from_file(cls, path: Path) -> "MetricCatalog":
        raw = json.loads(path.read_text(encoding="utf-8"))
        metrics: Dict[str, Metric] = {}
        for name, item in raw.get("metrics", {}).items():
            if name != item.get("name"):
                raise SemanticLayerError("指标 name 必须与配置键一致: %s" % name)
            for field in ("source_table", "expression", "dimensions", "time_grains"):
                if field not in item:
                    raise SemanticLayerError("指标 %s 缺少字段 %s" % (name, field))
            metrics[name] = Metric(
                name=name,
                display_name=item["display_name"],
                description=item["description"],
                source_table=item["source_table"],
                expression=item["expression"],
                dimensions=list(item["dimensions"]),
                time_grains=list(item["time_grains"]),
                synonyms=list(item.get("synonyms", [])),
                format=item.get("format", "number"),
            )
        if not metrics:
            raise SemanticLayerError("语义层中没有指标")
        return cls(metrics)

    def get(self, name: str) -> Metric:
        try:
            return self._metrics[name]
        except KeyError as exc:
            raise SemanticLayerError("未注册指标: %s" % name) from exc

    def names(self) -> List[str]:
        return sorted(self._metrics)

    def resolve(self, text: str) -> Optional[Metric]:
        """按名称、展示名或同义词匹配指标；多匹配时返回 None，交给上层澄清。"""
        normalized = text.strip().lower()
        matches = []
        for metric in self._metrics.values():
            candidates = [metric.name, metric.display_name] + metric.synonyms
            if any(normalized == candidate.lower() for candidate in candidates):
                matches.append(metric)
        return matches[0] if len(matches) == 1 else None

    def build_aggregate_query(
        self,
        metric_name: str,
        dimensions: Iterable[str] = (),
        time_grain: str = "month",
        start_date: str = "2025-01-01",
        end_date: str = "2025-12-31",
        filters: Optional[Mapping[str, str]] = None,
    ) -> str:
        metric = self.get(metric_name)
        dims = list(dimensions)
        if time_grain not in metric.time_grains:
            raise SemanticLayerError("指标 %s 不支持时间粒度 %s" % (metric_name, time_grain))
        unsupported = [dim for dim in dims if dim not in metric.dimensions]
        if unsupported:
            raise SemanticLayerError("指标 %s 不支持维度: %s" % (metric_name, ", ".join(unsupported)))
        filter_map = dict(filters or {})
        unsupported_filters = [dim for dim in filter_map if dim not in metric.dimensions]
        if unsupported_filters:
            raise SemanticLayerError("指标 %s 不支持过滤维度: %s" % (metric_name, ", ".join(unsupported_filters)))
        for identifier in [metric.source_table] + dims + list(filter_map):
            if not _IDENTIFIER.match(identifier):
                raise SemanticLayerError("非法 SQL 标识符: %s" % identifier)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", start_date) or not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
            raise SemanticLayerError("日期必须使用 YYYY-MM-DD 格式")

        select_parts = []
        group_parts = []
        if time_grain == "day":
            select_parts.append("sale_date")
            group_parts.append("sale_date")
        elif time_grain == "week":
            select_parts.append("date_trunc('week', sale_date) AS week_start")
            group_parts.append("date_trunc('week', sale_date)")
        elif time_grain == "month":
            select_parts.append("date_trunc('month', sale_date) AS month_start")
            group_parts.append("date_trunc('month', sale_date)")
        elif time_grain == "quarter":
            select_parts.append("date_trunc('quarter', sale_date) AS quarter_start")
            group_parts.append("date_trunc('quarter', sale_date)")
        for dim in dims:
            select_parts.append(dim)
            group_parts.append(dim)
        select_parts.append("%s AS value" % metric.expression)

        where_parts = ["sale_date BETWEEN DATE '%s' AND DATE '%s'" % (start_date, end_date)]
        where_parts.extend("%s = %s" % (key, _sql_literal(value)) for key, value in filter_map.items())
        return (
            "SELECT %s FROM %s "
            "WHERE %s "
            "GROUP BY %s ORDER BY %s"
            % (
                ", ".join(select_parts),
                metric.source_table,
                " AND ".join(where_parts),
                ", ".join(group_parts),
                ", ".join(group_parts),
            )
        )
