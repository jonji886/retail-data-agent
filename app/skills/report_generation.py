"""report_generation Skill：经营月报生成。

复用 RetailReportBuilder，调用已有 metric_query/anomaly/attribution 能力，
不重复写另一套指标计算代码。
"""

from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import QueryPlan
from app.reporting.weekly_report import RetailReportBuilder


def report_generation_skill(plan: QueryPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    root = context["root"]
    month = plan.report_month or (plan.start_date.strftime("%Y-%m") if plan.start_date else "2025-11")
    authorized_filters = context.get("authorized_filters", {})
    region_name = authorized_filters.get("region_name")
    store_id = authorized_filters.get("store_id")
    # 门店经理无法跨门店归因，默认拆解本门店内的品类贡献。
    dimension = plan.attribution_dimension or ("category_name" if store_id else "store_name")

    builder = RetailReportBuilder(root, data_source=context.get("data_source"))
    report_context = builder.build_context(month, region_name, dimension, store_id=store_id)
    markdown = builder.to_markdown(report_context)

    return {
        "skill": "report_generation",
        "success": True,
        "period": month,
        "scope": report_context.scope,
        "markdown": markdown,
        "kpis": [{"name": k.name, "display_name": k.display_name,
                  "current_value": k.current_value, "previous_value": k.previous_value,
                  "change_rate": k.change_rate, "format": k.format} for k in report_context.kpis],
        "anomaly_count": len(report_context.anomalies),
        "attribution_dimension": report_context.attribution.dimension,
        "tool_results": [],
    }
