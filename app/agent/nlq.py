"""中文自然语言问数的确定性基线。

该模块刻意不调用大模型，先把业务问题解析为可解释的结构化查询计划。
后续接入 LLM 时，模型输出仍应经过同一套语义层和只读 SQL 执行器校验。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from app.domain.time_range import resolve_relative_time
from app.semantic_layer.catalog import MetricCatalog, Metric
from app.tools.sql_runner import ReadOnlySQLRunner


class NLQError(ValueError):
    """用户问题暂时无法被可靠解析。"""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date
    time_grain: str
    label: str


@dataclass(frozen=True)
class ParsedQuestion:
    question: str
    metric: Metric
    dimensions: List[str]
    filters: Mapping[str, str]
    date_range: DateRange
    comparison: Optional[str]


@dataclass
class Answer:
    question: str
    parsed: ParsedQuestion
    sql: str
    rows: List[Dict[str, object]]
    explanation: str
    comparison_sql: Optional[str] = None


def _first_day(year: int, month: int) -> date:
    return date(year, month, 1)


def _last_day(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1).fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def _shift_year(value: date, offset: int) -> date:
    try:
        return value.replace(year=value.year + offset)
    except ValueError:
        return value.replace(year=value.year + offset, day=28)


def _json(path: Path) -> Mapping[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class NaturalLanguageQueryEngine:
    AS_OF_DATE = date(2025, 12, 31)

    def __init__(self, root: Path, reference_date: Optional[date] = None) -> None:
        self.root = root
        self.catalog = MetricCatalog.from_file(root / "configs" / "metrics" / "metrics.json")
        raw_dimensions = _json(root / "configs" / "dimensions.json")
        self.dimension_config = raw_dimensions["dimensions"]  # type: ignore[index]
        self.runner = ReadOnlySQLRunner(root / "data" / "retail.duckdb")
        self.reference_date = reference_date or self._latest_data_date()

    def _latest_data_date(self) -> date:
        rows = self.runner.query("SELECT MAX(sale_date) AS latest_date FROM fact_sales_daily")
        latest = rows[0].get("latest_date") if rows else None
        return latest if isinstance(latest, date) else self.AS_OF_DATE

    def parse(self, question: str) -> ParsedQuestion:
        clean = question.strip().rstrip("？?。！!")
        if not clean:
            raise NLQError("请输入经营分析问题")
        metric = self._match_metric(clean)
        dimensions = self._match_group_dimensions(clean)
        filters = self._match_filters(clean)
        date_range = self._match_date_range(clean)
        comparison = "yoy" if "同比" in clean else "mom" if "环比" in clean else None
        return ParsedQuestion(clean, metric, dimensions, filters, date_range, comparison)

    def answer(self, question: str) -> Answer:
        return self.answer_parsed(self.parse(question), question)

    def answer_parsed(self, parsed: ParsedQuestion, question: Optional[str] = None) -> Answer:
        current_sql = self.catalog.build_aggregate_query(
            parsed.metric.name,
            dimensions=parsed.dimensions,
            time_grain=parsed.date_range.time_grain,
            start_date=parsed.date_range.start.isoformat(),
            end_date=parsed.date_range.end.isoformat(),
            filters=parsed.filters,
        )
        current_rows = self.runner.query(current_sql)
        comparison_sql = None
        if parsed.comparison:
            previous = self._comparison_range(parsed.date_range, parsed.comparison)
            comparison_sql = self.catalog.build_aggregate_query(
                parsed.metric.name,
                dimensions=parsed.dimensions,
                time_grain=parsed.date_range.time_grain,
                start_date=previous.start.isoformat(),
                end_date=previous.end.isoformat(),
                filters=parsed.filters,
            )
            previous_rows = self.runner.query(comparison_sql)
            current_rows = self._merge_comparison(current_rows, previous_rows, parsed.date_range.time_grain)
        explanation = self._explain(parsed, current_rows)
        return Answer(question=question or parsed.question, parsed=parsed, sql=current_sql, rows=current_rows, explanation=explanation, comparison_sql=comparison_sql)

    def _match_metric(self, question: str) -> Metric:
        candidates: List[Tuple[int, Metric]] = []
        for name in self.catalog.names():
            metric = self.catalog.get(name)
            terms = [metric.display_name, metric.name] + metric.synonyms
            for term in terms:
                if term.lower() in question.lower():
                    candidates.append((len(term), metric))
        if not candidates:
            available = "、".join(self.catalog.get(name).display_name for name in self.catalog.names())
            raise NLQError("暂未识别指标。当前支持：%s" % available)
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _match_group_dimensions(self, question: str) -> List[str]:
        dimensions = []
        for name, config in self.dimension_config.items():
            terms = config.get("group_terms", [])  # type: ignore[union-attr]
            if any(term in question for term in terms):
                dimensions.append(name)
        return dimensions

    def _match_filters(self, question: str) -> Dict[str, str]:
        filters: Dict[str, str] = {}
        for name, config in self.dimension_config.items():
            values = list(config.get("values", []))  # type: ignore[union-attr]
            aliases = dict(config.get("aliases", {}))  # type: ignore[union-attr]
            for value in sorted(values, key=len, reverse=True):
                if value in question:
                    filters[name] = value
                    break
            if name not in filters:
                for alias, value in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
                    if alias in question:
                        filters[name] = value
                        break
        return filters

    def _match_date_range(self, question: str) -> DateRange:
        year_month = re.search(r"(20\d{2})年\s*(\d{1,2})月", question)
        if year_month:
            year, month = int(year_month.group(1)), int(year_month.group(2))
            return DateRange(_first_day(year, month), _last_day(year, month), "month", "%d年%d月" % (year, month))

        month_only = re.search(r"(?<!\d)(\d{1,2})月", question)
        if month_only:
            month = int(month_only.group(1))
            year = self.reference_date.year
            return DateRange(_first_day(year, month), _last_day(year, month), "month", "%d年%d月" % (year, month))

        if "每天" in question or "每日" in question or "按日" in question:
            return DateRange(self.reference_date.replace(day=1), self.reference_date, "day", "本月")
        if "每周" in question or "按周" in question:
            return DateRange(self.reference_date.replace(day=1), self.reference_date, "week", "本月")

        try:
            relative = resolve_relative_time(question, self.reference_date)
        except ValueError as exc:
            raise NLQError(str(exc)) from exc
        if relative:
            return DateRange(
                relative.start_date,
                relative.end_date,
                relative.grain,
                relative.label,
            )
        return DateRange(self.reference_date.replace(day=1), self.reference_date, "month", "本月")

    def _comparison_range(self, current: DateRange, comparison: str) -> DateRange:
        if comparison == "yoy":
            return DateRange(_shift_year(current.start, -1), _shift_year(current.end, -1), current.time_grain, "去年同期")
        previous_start = _shift_month(current.start, -1)
        previous_end = _last_day(previous_start.year, previous_start.month) if current.time_grain == "month" else _shift_month(current.end, -1)
        return DateRange(previous_start, previous_end, current.time_grain, "上月")

    @staticmethod
    def _merge_comparison(current: Sequence[Mapping[str, object]], previous: Sequence[Mapping[str, object]], time_grain: str) -> List[Dict[str, object]]:
        time_columns = {"month_start", "week_start", "sale_date", "quarter_start"}

        def dimension_key(row: Mapping[str, object]) -> Tuple[object, ...]:
            keys = [name for name in row if name not in time_columns and name != "value"]
            return tuple(row[name] for name in keys)

        previous_groups: Dict[Tuple[object, ...], List[Mapping[str, object]]] = {}
        current_groups: Dict[Tuple[object, ...], List[Mapping[str, object]]] = {}
        for row in previous:
            previous_groups.setdefault(dimension_key(row), []).append(row)
        for row in current:
            current_groups.setdefault(dimension_key(row), []).append(row)
        merged: List[Dict[str, object]] = []
        for dimension, current_group in current_groups.items():
            previous_group = previous_groups.get(dimension, [])
            for index, row in enumerate(current_group):
                old = previous_group[index] if index < len(previous_group) else {}
                current_value = float(row.get("value") or 0)
                previous_value = float(old.get("value") or 0)
                change = current_value - previous_value
                merged_row = dict(row)
                merged_row.pop("value", None)
                merged_row["current_value"] = current_value
                merged_row["comparison_value"] = previous_value
                merged_row["change"] = change
                merged_row["change_rate"] = change / previous_value if previous_value else None
                merged.append(merged_row)
        return merged

    @staticmethod
    def _explain(parsed: ParsedQuestion, rows: Sequence[Mapping[str, object]]) -> str:
        filters = "、".join("%s=%s" % (key, value) for key, value in parsed.filters.items()) or "全部范围"
        group = "、".join(parsed.dimensions) or "整体"
        if parsed.comparison:
            return "%s在%s按%s分析%s，已返回当前值、对比值、变化额和变化率，共%d条结果。" % (
                parsed.metric.display_name,
                parsed.date_range.label,
                group,
                "（%s）" % filters,
                len(rows),
            )
        return "%s在%s按%s分析（%s），共%d条结果。" % (parsed.metric.display_name, parsed.date_range.label, group, filters, len(rows))
