"""把 Agent 的已校验结果整理成面向经营管理者的展示模型。

本模块只做展示层的数据整理，不重新计算指标，也不改变权限范围。
业务因果仍需外部事实验证；归因结果只表示数据变化贡献。
"""

from __future__ import annotations

from typing import Any, Dict, List


_DIMENSION_LABELS = {
    "city_name": "城市",
    "store_name": "门店",
    "category_name": "品类",
    "brand_name": "品牌",
    "channel_name": "渠道",
}


def dimension_label(dimension: Any) -> str:
    """把内部维度名转换为业务用户可读的名称。"""
    value = str(dimension or "")
    return _DIMENSION_LABELS.get(value, value or "因素")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_attribution_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """返回归因结果的业务展示摘要。"""
    current_total = _number(result.get("current_total"))
    comparison_total = _number(result.get("comparison_total"))
    total_delta = _number(result.get("total_delta"))
    change_rate = total_delta / comparison_total if comparison_total else None
    direction = "下降" if total_delta < 0 else "增长" if total_delta > 0 else "持平"
    top_negative = [
        {
            **item,
            "delta": _number(item.get("delta")),
            "contribution_rate": item.get("contribution_rate"),
            "dimension_label": dimension_label(item.get("dimension") or result.get("dimension")),
        }
        for item in result.get("top_negative", [])
    ]
    top_two_contribution = sum(
        _number(item.get("contribution_rate")) for item in top_negative[:2]
    )
    return {
        "scope": result.get("scope") or "当前权限范围",
        "current_period": result.get("current_period") or "",
        "comparison_period": result.get("comparison_period") or "",
        "current_total": current_total,
        "comparison_total": comparison_total,
        "total_delta": total_delta,
        "change_rate": change_rate,
        "direction": direction,
        "dimension_label": dimension_label(result.get("dimension")),
        "top_negative": top_negative,
        "top_two_contribution": top_two_contribution,
        "limitations": result.get(
            "limitations", "贡献率表示数据变化贡献，不等同于已验证的业务因果。"
        ),
    }


def build_attribution_table(summary: Dict[str, Any], limit: int = 5) -> List[Dict[str, Any]]:
    """生成归因表格的数值模型，格式化交给 UI 层处理。"""
    rows: List[Dict[str, Any]] = []
    for item in summary.get("top_negative", [])[:limit]:
        rows.append({
            "成员": item.get("member", ""),
            "维度": item.get("dimension_label", "因素"),
            "当前值": _number(item.get("current_value")),
            "对比值": _number(item.get("comparison_value")),
            "变化额": _number(item.get("delta")),
            "下降金额": abs(_number(item.get("delta"))),
            "下降贡献": item.get("contribution_rate"),
        })
    return rows


def build_follow_up_questions(summary: Dict[str, Any]) -> List[str]:
    """基于当前归因结果生成可继续追问的业务问题。"""
    scope = summary.get("scope", "当前范围")
    dimension = summary.get("dimension_label", "因素")
    return [
        "%s下降最多的%s，主要是订单数还是客单价导致的？" % (scope, dimension),
        "%s下降最多的品类是什么？" % scope,
        "查看%s过去 6 个月销售额趋势。" % scope,
    ]
