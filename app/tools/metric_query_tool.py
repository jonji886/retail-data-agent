"""Metric Query Tool：封装语义层 + 只读 SQL 执行器，作为 Agent 访问数据的统一入口。

不引入新的指标计算逻辑，仅复用 MetricCatalog.build_aggregate_query + ReadOnlySQLRunner。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.agent.contracts import ErrorType, ToolResult
from app.semantic_layer.catalog import MetricCatalog, SemanticLayerError
from app.tools.sql_runner import ReadOnlySQLRunner, SQLSafetyError


def _month_range(year: int, month: int) -> Tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        return start, date(year, 12, 31)
    from datetime import timedelta
    return start, date(year, month + 1, 1) - timedelta(days=1)


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def _shift_year(value: date, offset: int) -> date:
    try:
        return value.replace(year=value.year + offset)
    except ValueError:
        return value.replace(year=value.year + offset, day=28)


def comparison_range(start: date, end: date, comparison: str) -> Tuple[date, date]:
    """根据对比方式返回对比期 [start, end]。"""
    if comparison == "yoy":
        return _shift_year(start, -1), _shift_year(end, -1)
    # mom: 上一期同长度
    prev_start = _shift_month(start, -1)
    if start.day == 1 and end.day >= 27:  # 整月
        prev_end = _month_range(prev_start.year, prev_start.month)[1]
    else:
        prev_end = _shift_month(end, -1)
    return prev_start, prev_end


class MetricQueryTool:
    """通过语义层生成只读 SQL 并执行，返回结构与 ToolResult 对齐。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.catalog = MetricCatalog.from_file(root / "configs" / "metrics" / "metrics.json")
        self.runner = ReadOnlySQLRunner(root / "data" / "retail.duckdb")

    def query(
        self,
        metric: str,
        dimensions: Optional[List[str]] = None,
        time_grain: str = "month",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        filters: Optional[Mapping[str, str]] = None,
        comparison: Optional[str] = None,
    ) -> ToolResult:
        dims = list(dimensions or [])
        filter_map = dict(filters or {})
        try:
            current_sql = self.catalog.build_aggregate_query(
                metric, dimensions=dims, time_grain=time_grain,
                start_date=start_date or "2025-01-01", end_date=end_date or "2025-12-31",
                filters=filter_map,
            )
        except SemanticLayerError as exc:
            return ToolResult(
                success=False,
                error_type=ErrorType.INVALID_METRIC if "不支持" in str(exc) else ErrorType.INVALID_PLAN,
                error_message=str(exc),
                metadata={"metric": metric, "dimensions": dims, "filters": filter_map},
            )
        try:
            current_rows = self.runner.query(current_sql)
        except SQLSafetyError as exc:
            return ToolResult(
                success=False,
                error_type=exc.reason_code,
                error_message="查询被安全策略拒绝：%s" % exc,
                metadata={
                    "sql": current_sql,
                    "reason_code": exc.reason_code,
                    "guard_stage": exc.guard_stage,
                },
            )
        except Exception:  # noqa: BLE001
            return ToolResult(
                success=False,
                error_type=ErrorType.QUERY_ERROR,
                error_message="SQL 查询执行失败",
                metadata={"sql": current_sql, "reason_code": "query_execution_failed"},
            )

        comparison_sql: Optional[str] = None
        merged_rows: List[Dict[str, Any]] = current_rows
        if comparison:
            try:
                cs = date.fromisoformat(start_date)  # type: ignore[arg-type]
                ce = date.fromisoformat(end_date)    # type: ignore[arg-type]
                ps, pe = comparison_range(cs, ce, comparison)
                comparison_sql = self.catalog.build_aggregate_query(
                    metric, dimensions=dims, time_grain=time_grain,
                    start_date=ps.isoformat(), end_date=pe.isoformat(), filters=filter_map,
                )
                previous_rows = self.runner.query(comparison_sql)
                merged_rows = self._merge_comparison(current_rows, previous_rows, time_grain)
            except SQLSafetyError as exc:
                return ToolResult(
                    success=False,
                    error_type=exc.reason_code,
                    error_message="对比查询被安全策略拒绝：%s" % exc,
                    metadata={
                        "sql": comparison_sql,
                        "reason_code": exc.reason_code,
                        "guard_stage": exc.guard_stage,
                    },
                )
            except Exception:  # noqa: BLE001
                # 对比失败不致命，保留当前值
                pass

        metric_def = self.catalog.get(metric)
        return ToolResult(
            success=True,
            data={
                "metric": metric,
                "metric_definition": metric_def.description,
                "metric_display_name": metric_def.display_name,
                "rows": merged_rows,
                "sql": current_sql,
                "comparison_sql": comparison_sql,
                "time_range": {"start": start_date, "end": end_date},
                "comparison": comparison,
            },
            metadata={"row_count": len(merged_rows)},
        )

    @staticmethod
    def _merge_comparison(
        current: List[Dict[str, Any]],
        previous: List[Dict[str, Any]],
        time_grain: str,
    ) -> List[Dict[str, Any]]:
        """合并当前期与对比期，附加 current_value/comparison_value/change/change_rate。"""
        time_columns = {"month_start", "week_start", "sale_date", "quarter_start"}

        def dim_key(row: Mapping[str, Any]) -> Tuple[Any, ...]:
            return tuple(v for k, v in row.items() if k not in time_columns and k != "value")

        prev_groups: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = {}
        cur_groups: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = {}
        for row in previous:
            prev_groups.setdefault(dim_key(row), []).append(row)
        for row in current:
            cur_groups.setdefault(dim_key(row), []).append(row)

        merged: List[Dict[str, Any]] = []
        for dim, cur_group in cur_groups.items():
            prev_group = prev_groups.get(dim, [])
            for idx, row in enumerate(cur_group):
                old = prev_group[idx] if idx < len(prev_group) else {}
                cv = float(row.get("value") or 0)
                pv = float(old.get("value") or 0)
                change = cv - pv
                merged_row = dict(row)
                merged_row.pop("value", None)
                merged_row["current_value"] = cv
                merged_row["comparison_value"] = pv
                merged_row["change"] = change
                merged_row["change_rate"] = change / pv if pv else None
                merged.append(merged_row)
        return merged
