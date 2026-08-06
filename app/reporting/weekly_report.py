"""经营报告：确定性数据汇总 + 可选的大模型文字组织。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import duckdb

from app.analytics.anomaly import Anomaly, SalesAnomalyDetector
from app.analytics.attribution import AttributionResult, SalesAttributor
from app.llm.deepseek_client import DeepSeekClient


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


@dataclass(frozen=True)
class KPI:
    name: str
    display_name: str
    current_value: float
    previous_value: float
    change_rate: Optional[float]
    format: str


@dataclass(frozen=True)
class ReportContext:
    company: str
    report_type: str
    period: str
    comparison_period: str
    scope: str
    kpis: List[KPI]
    trend: List[Mapping[str, Any]]
    anomalies: List[Anomaly]
    attribution: AttributionResult

    def as_dict(self) -> Dict[str, Any]:
        return {
            "company": self.company,
            "report_type": self.report_type,
            "period": self.period,
            "comparison_period": self.comparison_period,
            "scope": self.scope,
            "kpis": [asdict(item) for item in self.kpis],
            "trend": list(self.trend),
            "anomalies": [asdict(item) for item in self.anomalies],
            "attribution": {
                "scope": self.attribution.scope,
                "current_period": self.attribution.current_period,
                "comparison_period": self.attribution.comparison_period,
                "current_total": self.attribution.current_total,
                "comparison_total": self.attribution.comparison_total,
                "total_delta": self.attribution.total_delta,
                "dimension": self.attribution.dimension,
                "contributions": [asdict(item) for item in self.attribution.contributions],
            },
        }


class RetailReportBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.database_path = root / "data" / "retail.duckdb"

    def build_context(
        self,
        month: str,
        region_name: Optional[str] = None,
        attribution_dimension: str = "store_name",
    ) -> ReportContext:
        previous_month = _previous_month(month)
        current_start, current_end = _month_range(month)
        previous_start, previous_end = _month_range(previous_month)
        scope = region_name or "全部区域"
        kpis = self._load_kpis(current_start, current_end, previous_start, previous_end, region_name)
        trend = self._load_trend(month, region_name)
        anomalies = SalesAnomalyDetector(self.database_path).detect(month, entity_level="region")
        if region_name:
            anomalies = [item for item in anomalies if item.entity_name == region_name]
        attribution = SalesAttributor(self.database_path).analyze(month, attribution_dimension, region_name)
        return ReportContext(
            company="优选生活",
            report_type="经营分析月报",
            period=month,
            comparison_period=previous_month,
            scope=scope,
            kpis=kpis,
            trend=trend,
            anomalies=anomalies,
            attribution=attribution,
        )

    def _load_kpis(
        self,
        current_start: date,
        current_end: date,
        previous_start: date,
        previous_end: date,
        region_name: Optional[str],
    ) -> List[KPI]:
        scope_sql = ""
        params: List[str] = [current_start.isoformat(), current_end.isoformat()]
        if region_name:
            scope_sql = " AND region_name = ?"
            params.append(region_name)
        params.extend([previous_start.isoformat(), previous_end.isoformat()])
        if region_name:
            params.append(region_name)
        query = (
            "SELECT period, SUM(sales_amount), SUM(order_count), SUM(gross_profit), "
            "SUM(sales_amount) / NULLIF(SUM(order_count), 0) "
            "FROM ("
            "SELECT 'current' AS period, sales_amount, order_count, gross_profit FROM v_sales_enriched "
            "WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s "
            "UNION ALL "
            "SELECT 'previous' AS period, sales_amount, order_count, gross_profit FROM v_sales_enriched "
            "WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s"
            ") GROUP BY 1 ORDER BY 1"
            % (scope_sql, scope_sql)
        )
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        values: Dict[str, Tuple[float, float, float, float]] = {}
        for period, sales, orders, profit, average_order_value in rows:
            values[str(period)] = (float(sales or 0), float(orders or 0), float(profit or 0), float(average_order_value or 0))
        current = values.get("current", (0.0, 0.0, 0.0, 0.0))
        previous = values.get("previous", (0.0, 0.0, 0.0, 0.0))
        metrics = [
            ("sales_amount", "销售额", current[0], previous[0], "currency"),
            ("order_count", "订单数", current[1], previous[1], "integer"),
            ("gross_profit", "毛利额", current[2], previous[2], "currency"),
            ("average_order_value", "客单价", current[3], previous[3], "currency"),
        ]
        return [
            KPI(name, display_name, current_value, previous_value, (current_value - previous_value) / previous_value if previous_value else None, metric_format)
            for name, display_name, current_value, previous_value, metric_format in metrics
        ]

    def _load_trend(self, month: str, region_name: Optional[str]) -> List[Mapping[str, Any]]:
        end = _month_range(month)[1]
        start_month = month
        for _ in range(5):
            start_month = _previous_month(start_month)
        start = _month_range(start_month)[0]
        scope_sql = ""
        params: List[str] = [start.isoformat(), end.isoformat()]
        if region_name:
            scope_sql = " AND region_name = ?"
            params.append(region_name)
        query = (
            "SELECT strftime(date_trunc('month', sale_date), '%%Y-%%m') AS period, "
            "SUM(sales_amount) AS sales_amount, SUM(gross_profit) / NULLIF(SUM(sales_amount), 0) AS gross_margin_rate "
            "FROM v_sales_enriched WHERE sale_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)%s "
            "GROUP BY 1 ORDER BY 1" % scope_sql
        )
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        return [
            {"period": str(period), "sales_amount": float(sales_amount or 0), "gross_margin_rate": float(margin or 0)}
            for period, sales_amount, margin in rows
        ]

    @staticmethod
    def to_markdown(context: ReportContext) -> str:
        lines = [
            "# %s - %s" % (context.company, context.report_type),
            "",
            "> 分析期间：%s；对比期间：%s；分析范围：%s" % (context.period, context.comparison_period, context.scope),
            "",
            "## 一、经营摘要",
            "",
        ]
        sales_kpi = next(item for item in context.kpis if item.name == "sales_amount")
        direction = "增长" if (sales_kpi.change_rate or 0) >= 0 else "下降"
        lines.append("本期销售额为 %.2f，较上期%s %.2f%%。" % (sales_kpi.current_value, direction, abs((sales_kpi.change_rate or 0) * 100)))
        if context.anomalies:
            lines.append("检测到 %d 项销售异常，最高等级为 %s。" % (len(context.anomalies), context.anomalies[0].severity.upper()))
        else:
            lines.append("本期未检测到超过规则阈值的区域销售异常。")
        lines.extend(["", "## 二、核心指标", "", "| 指标 | 本期 | 上期 | 变化率 |", "|---|---:|---:|---:|"])
        for item in context.kpis:
            current = "%.2f" % item.current_value
            previous = "%.2f" % item.previous_value
            rate = "N/A" if item.change_rate is None else "%.2f%%" % (item.change_rate * 100)
            lines.append("| %s | %s | %s | %s |" % (item.display_name, current, previous, rate))
        lines.extend(["", "## 三、趋势", "", "| 月份 | 销售额 | 毛利率 |", "|---|---:|---:|"])
        for item in context.trend:
            lines.append("| %s | %.2f | %.2f%% |" % (item["period"], item["sales_amount"], item["gross_margin_rate"] * 100))
        lines.extend(["", "## 四、异常预警", ""])
        if context.anomalies:
            for item in context.anomalies:
                lines.append("- **[%s] %s**：销售额 %.2f，前三个月基线 %.2f，变化率 %.2f%%；规则：%s。" % (
                    item.severity.upper(), item.entity_name, item.current_value, item.baseline_value, item.change_rate * 100, item.rule
                ))
        else:
            lines.append("- 暂无异常预警。")
        lines.extend(["", "## 五、销售变化归因", "", "当前销售额较上期变化 %.2f。" % context.attribution.total_delta, ""])
        if context.attribution.top_negative:
            for item in context.attribution.top_negative:
                rate = "N/A" if item.contribution_rate is None else "%.2f%%" % (item.contribution_rate * 100)
                lines.append("- %s **%s**：变化额 %.2f，贡献率 %s。" % (item.dimension, item.member, item.delta, rate))
        else:
            lines.append("- 未发现负向贡献因素。")
        lines.extend(["", "## 六、口径与限制", "", "- 指标来自 DuckDB 中的虚拟零售数据。", "- 归因结果表示数据变化贡献，不等同于已验证的业务因果。", "- 建议结合促销、库存和门店经营记录进行人工确认。", ""])
        return "\n".join(lines)

    @staticmethod
    def to_deepseek_markdown(context: ReportContext, client: DeepSeekClient) -> str:
        system_prompt = (
            "你是企业经营分析报告撰写助手。根据用户提供的已验证 JSON 数据生成中文 Markdown 月报。\n"
            "只使用输入中的数字和事实，不得改写、补充或猜测任何数据。\n"
            "必须包含：经营摘要、核心指标、趋势、异常预警、销售变化归因、建议行动、口径与限制。\n"
            "归因只能表述为数据贡献因素，不能声称已证明因果。\n"
            "建议行动必须与异常或负向贡献因素对应；没有证据时明确写‘需要人工确认’。\n"
            "只返回 Markdown 正文，不要返回代码块或解释。"
        )
        user_prompt = json.dumps(context.as_dict(), ensure_ascii=False, indent=2)
        return client.complete_text(system_prompt, user_prompt, max_tokens=2400)
