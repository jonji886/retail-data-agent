"""metric_query Skill：单指标查询（含可选同比/环比对比）。

组合 MetricQueryTool，返回结构化结果。
不引入新的指标计算逻辑，完全复用语义层。
"""

from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import QueryPlan
from app.tools.metric_query_tool import MetricQueryTool


def metric_query_skill(plan: QueryPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    root = context["root"]
    authorized_filters = context.get("authorized_filters", dict(plan.filters))
    tool = MetricQueryTool(root)
    result = tool.query(
        metric=plan.metric,
        dimensions=plan.dimensions,
        time_grain=plan.time_grain,
        start_date=plan.start_date.isoformat() if plan.start_date else None,
        end_date=plan.end_date.isoformat() if plan.end_date else None,
        filters=authorized_filters,
        comparison=plan.comparison,
    )
    if not result.success:
        return {
            "skill": "metric_query",
            "success": False,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "tool_results": [result.to_dict()],
        }
    return {
        "skill": "metric_query",
        "success": True,
        "metric": result.data["metric"],
        "metric_display_name": result.data["metric_display_name"],
        "metric_definition": result.data["metric_definition"],
        "rows": result.data["rows"],
        "sql": result.data["sql"],
        "comparison_sql": result.data["comparison_sql"],
        "time_range": result.data["time_range"],
        "comparison": result.data["comparison"],
        "row_count": result.metadata["row_count"],
        "tool_results": [result.to_dict()],
    }
