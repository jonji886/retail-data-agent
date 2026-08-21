"""trend_analysis Skill：单指标连续时间粒度趋势。

复用 MetricQueryTool，以多期 month 粒度查询，返回趋势序列。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

from app.agent.contracts import QueryPlan
from app.tools.metric_query_tool import MetricQueryTool, _shift_month


def trend_analysis_skill(plan: QueryPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    root = context["root"]
    authorized_filters = context.get("authorized_filters", dict(plan.filters))
    tool = MetricQueryTool(root)

    # 默认取最近 6 个月趋势
    end = plan.end_date or date(2025, 12, 31)
    months = 6
    start = _shift_month(end.replace(day=1), -(months - 1))

    result = tool.query(
        metric=plan.metric,
        dimensions=plan.dimensions,
        time_grain="month",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        filters=authorized_filters,
        comparison=None,
    )
    if not result.success:
        return {
            "skill": "trend_analysis",
            "success": False,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "tool_results": [result.to_dict()],
        }
    rows = result.data["rows"]
    # 计算整体变化率（首尾）
    values = [float(r.get("value") or 0) for r in rows]
    first = values[0] if values else 0
    last = values[-1] if values else 0
    overall_change_rate = (last - first) / first if first else None
    return {
        "skill": "trend_analysis",
        "success": True,
        "metric": result.data["metric"],
        "metric_display_name": result.data["metric_display_name"],
        "metric_definition": result.data["metric_definition"],
        "rows": rows,
        "sql": result.data["sql"],
        "time_range": result.data["time_range"],
        "trend_points": len(rows),
        "first_value": first,
        "last_value": last,
        "overall_change_rate": overall_change_rate,
        "tool_results": [result.to_dict()],
    }
