"""Skill 层：面向业务目标的复合能力，默认是确定性 Python 业务逻辑。

每个 Skill 接收 QueryPlan 和上下文，返回结构化结果 dict。
Skill 可以组合多个 Tool，但不实现为独立 LLM Agent。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from app.agent.contracts import QueryPlan
from app.skills.metric_query import metric_query_skill
from app.skills.trend_analysis import trend_analysis_skill
from app.skills.anomaly_analysis import anomaly_analysis_skill
from app.skills.attribution_analysis import attribution_analysis_skill
from app.skills.report_generation import report_generation_skill


SkillFunc = Callable[[QueryPlan, Dict[str, Any]], Dict[str, Any]]


SKILL_REGISTRY: Dict[str, SkillFunc] = {
    "metric_query": metric_query_skill,
    "trend_analysis": trend_analysis_skill,
    "anomaly_analysis": anomaly_analysis_skill,
    "attribution_analysis": attribution_analysis_skill,
    "report_generation": report_generation_skill,
}


def get_skill(intent: str) -> SkillFunc:
    """根据 intent 获取对应 Skill。不存在时抛出 KeyError。"""
    if intent not in SKILL_REGISTRY:
        raise KeyError("没有注册的 Skill：%s" % intent)
    return SKILL_REGISTRY[intent]
