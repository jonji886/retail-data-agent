"""anomaly_analysis Skill：销售异常检测。

复用 SalesAnomalyDetector，LLM 不参与数学判断，只解释已计算出的异常。
"""

from __future__ import annotations

from typing import Any, Dict

from app.agent.contracts import ErrorType, QueryPlan
from app.analytics.anomaly import SalesAnomalyDetector
from app.dataclasses_compat import asdict_safe


def anomaly_analysis_skill(plan: QueryPlan, context: Dict[str, Any]) -> Dict[str, Any]:
    root = context["root"]
    database_path = root / "data" / "retail.duckdb"
    month = plan.report_month or (plan.start_date.strftime("%Y-%m") if plan.start_date else "2025-11")
    authorized_filters = context.get("authorized_filters", {})
    region_name = authorized_filters.get("region_name")
    store_id = authorized_filters.get("store_id")
    # 门店经理按门店粒度检测，区域/总部按区域粒度检测，均在 SQL 层限定权限范围。
    entity_level = "store" if store_id else "region"

    detector = SalesAnomalyDetector(database_path, data_source=context.get("data_source"))
    try:
        anomalies = detector.detect(
            month,
            entity_level=entity_level,
            region_name=region_name,
            store_id=store_id,
        )
    except ValueError as exc:
        return {
            "skill": "anomaly_analysis",
            "success": False,
            "error_type": ErrorType.INVALID_PLAN,
            "error_message": str(exc),
            "tool_results": [],
        }

    return {
        "skill": "anomaly_analysis",
        "success": True,
        "month": month,
        "anomalies": [asdict_safe(a) for a in anomalies],
        "anomaly_count": len(anomalies),
        "has_anomaly": bool(anomalies),
        "tool_results": [],
    }
