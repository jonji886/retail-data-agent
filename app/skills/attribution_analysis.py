"""attribution_analysis Skill：销售变化贡献度拆解。

复用 SalesAttributor。LLM 只解释已计算出的贡献结果。
明确区分 contribution ≠ causality。
"""

from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import ErrorType, QueryPlan
from app.analytics.attribution import SalesAttributor
from app.dataclasses_compat import asdict_safe


def attribution_analysis_skill(plan: QueryPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    root = context["root"]
    database_path = root / "data" / "retail.duckdb"
    month = plan.report_month or (plan.start_date.strftime("%Y-%m") if plan.start_date else "2025-11")
    authorized_filters = context.get("authorized_filters", {})
    region_name = authorized_filters.get("region_name")
    store_id = authorized_filters.get("store_id")
    # 门店经理无法跨门店归因，默认拆解本门店内的品类贡献。
    dimension = plan.attribution_dimension or ("category_name" if store_id else "store_name")

    attributor = SalesAttributor(database_path)
    try:
        result = attributor.analyze(month, dimension=dimension, region_name=region_name, store_id=store_id)
    except ValueError as exc:
        return {
            "skill": "attribution_analysis",
            "success": False,
            "error_type": ErrorType.INVALID_DIMENSION,
            "error_message": str(exc),
            "tool_results": [],
        }

    return {
        "skill": "attribution_analysis",
        "success": True,
        "scope": result.scope,
        "current_period": result.current_period,
        "comparison_period": result.comparison_period,
        "current_total": result.current_total,
        "comparison_total": result.comparison_total,
        "total_delta": result.total_delta,
        "dimension": result.dimension,
        "contributions": [asdict_safe(c) for c in result.contributions],
        "top_negative": [asdict_safe(c) for c in result.top_negative],
        "limitations": "贡献率表示数据变化贡献，不等同于已验证的业务因果。",
        "tool_results": [],
    }
