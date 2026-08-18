"""parse_request 节点：Question → Intent → QueryPlan。

优先复用现有 NaturalLanguageQueryEngine / DeepSeekNLQEngine。
LLM 不可用时保持 deterministic baseline 可独立运行。
增加 intent 识别（现有引擎只识别 metric_query，需扩展到 attribution/anomaly/report）。
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.agent.contracts import ErrorType, Intent, QueryPlan
from app.agent.nlq import DateRange, NLQError, NaturalLanguageQueryEngine
from app.agent.state import AgentState
from app.tools.metadata import MetadataTool


# ---------------------------------------------------------------------------
# Intent 识别（确定性规则，不调用 LLM）
# ---------------------------------------------------------------------------

_INTENT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    Intent.ATTRIBUTION_ANALYSIS: ("为什么", "原因", "下降的原因", "增长的原因", "归因", "拖累", "贡献"),
    Intent.ANOMALY_ANALYSIS: ("异常", "预警", "报警", "预警情况", "有没有异常"),
    Intent.REPORT_GENERATION: ("报告", "月报", "周报", "日报", "经营分析报告", "生成报告"),
    Intent.TREND_ANALYSIS: ("趋势", "走势", "过去几个月", "近几个月", "变化趋势"),
}


def _detect_intent(question: str, engine: NaturalLanguageQueryEngine) -> str:
    """确定性 intent 识别：先匹配关键词，再回退到 metric_query。

    优先级：attribution > anomaly > report > trend > metric_query。
    attribution 关键词最具体，应优先于 trend（"趋势"也可能出现在归因问题中）。
    """
    clean = question.strip()
    for intent in (Intent.ATTRIBUTION_ANALYSIS, Intent.ANOMALY_ANALYSIS,
                   Intent.REPORT_GENERATION, Intent.TREND_ANALYSIS):
        for keyword in _INTENT_KEYWORDS[intent]:
            if keyword in clean:
                return intent
    # 默认 metric_query（如果指标可识别）
    try:
        engine.parse(clean)
        return Intent.METRIC_QUERY
    except NLQError:
        return Intent.UNSUPPORTED


def _resolve_month_from_question(question: str, latest: Optional[date]) -> str:
    """从问题中提取 YYYY-MM，默认使用 latest_data_date 所在月。"""
    import re
    m = re.search(r"(20\d{2})年\s*(\d{1,2})月", question)
    if m:
        return "%04d-%02d" % (int(m.group(1)), int(m.group(2)))
    m = re.search(r"(?<!\d)(\d{1,2})月", question)
    if m and latest:
        return "%04d-%02d" % (latest.year, int(m.group(1)))
    if latest:
        return latest.strftime("%Y-%m")
    return "2025-11"


def _resolve_region(filters: Dict[str, str]) -> Optional[str]:
    return filters.get("region_name")


# ---------------------------------------------------------------------------
# 节点实现
# ---------------------------------------------------------------------------

def parse_request(state: AgentState) -> AgentState:
    """解析用户问题为 intent + QueryPlan。

    支持两条链路：
    - LLM Enhanced（如果 context 配置了 use_llm=True 且 API 可用）
    - Deterministic Baseline（默认）
    """
    root = state.get("_root")  # type: ignore[assignment]
    if root is None:
        # 允许通过 context 传入 root
        root = Path(".")
    root = Path(root)
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    question = state.get("question", "")

    engine = NaturalLanguageQueryEngine(root)
    use_llm = state.get("_use_llm", False)  # type: ignore[assignment]
    metadata_tool = MetadataTool(root / "data" / "retail.duckdb")
    latest = metadata_tool.latest_date()

    intent = _detect_intent(question, engine)

    # 记录 trace
    events = list(state.get("trace_events", []))
    events.append({
        "trace_id": trace_id, "node": "parse_request",
        "start_at": started, "end_at": time.monotonic(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status": "success", "intent": intent,
    })

    if intent == Intent.UNSUPPORTED:
        return {
            **state,
            "intent": Intent.UNSUPPORTED,
            "query_plan": {},
            "error_type": ErrorType.UNSUPPORTED_INTENT,
            "error_message": "暂不支持该类问题。当前支持：指标查询、趋势分析、异常检测、归因分析、报告生成。",
            "trace_events": events,
        }

    # 对于 metric_query / trend，复用现有引擎的解析
    if intent in (Intent.METRIC_QUERY, Intent.TREND_ANALYSIS):
        try:
            if use_llm:
                from app.agent.llm_nlq import DeepSeekNLQEngine, LLMPlanError
                try:
                    llm_engine = DeepSeekNLQEngine(root)
                    parsed = llm_engine.parse(question) if hasattr(llm_engine, "parse") else None
                    # DeepSeekNLQEngine 没有 parse 方法，用 answer 的内部逻辑
                    # 直接构造 plan
                    plan_json_str = llm_engine.client.complete_json(
                        llm_engine._system_prompt(), question
                    )
                    plan_dict = llm_engine._parse_json(plan_json_str)
                    parsed = llm_engine._build_parsed_question(question, plan_dict)
                    llm_calls = list(state.get("llm_calls", []))
                    llm_calls.append({
                        "provider": "deepseek", "node": "parse_request",
                        "status": "success", "prompt_version": "v1",
                    })
                    state = {**state, "llm_calls": llm_calls}  # type: ignore[assignment]
                except (RuntimeError, LLMPlanError) as exc:
                    # LLM 不可用，回退到确定性
                    parsed = engine.parse(question)
                    llm_calls = list(state.get("llm_calls", []))
                    llm_calls.append({
                        "provider": "deepseek", "node": "parse_request",
                        "status": "fallback", "error": str(exc),
                    })
                    state = {**state, "llm_calls": llm_calls}  # type: ignore[assignment]
            else:
                parsed = engine.parse(question)
        except NLQError as exc:
            events.append({
                "trace_id": trace_id, "node": "parse_request",
                "status": "error", "error": str(exc),
            })
            return {
                **state, "intent": Intent.UNSUPPORTED, "query_plan": {},
                "error_type": ErrorType.INVALID_PLAN, "error_message": str(exc),
                "trace_events": events,
            }
        plan = QueryPlan(
            intent=intent,
            metric=parsed.metric.name,
            dimensions=list(parsed.dimensions),
            filters=dict(parsed.filters),
            time_grain=parsed.date_range.time_grain,
            start_date=parsed.date_range.start,
            end_date=parsed.date_range.end,
            comparison=parsed.comparison,
        )
        return {**state, "intent": intent, "query_plan": plan.to_dict(), "trace_events": events}

    # 对于 attribution / anomaly / report，提取月份和区域
    month = _resolve_month_from_question(question, latest)
    # 尝试从问题中提取区域
    filters: Dict[str, str] = {}
    try:
        parsed_for_filters = engine.parse(question)
        filters = dict(parsed_for_filters.filters)
    except NLQError:
        pass
    region = _resolve_region(filters)
    metric = "sales_amount"
    try:
        parsed_for_metric = engine.parse(question)
        metric = parsed_for_metric.metric.name
    except NLQError:
        pass

    if intent == Intent.ATTRIBUTION_ANALYSIS:
        plan = QueryPlan(
            intent=intent, metric=metric, filters=filters,
            report_month=month, attribution_dimension="store_name",
            start_date=date.fromisoformat(month + "-01"),
            end_date=_month_end(month),
        )
    elif intent == Intent.ANOMALY_ANALYSIS:
        plan = QueryPlan(
            intent=intent, metric=metric, filters=filters,
            report_month=month,
            start_date=date.fromisoformat(month + "-01"),
            end_date=_month_end(month),
        )
    else:  # report
        plan = QueryPlan(
            intent=intent, metric=metric, filters=filters,
            report_month=month, attribution_dimension="store_name",
        )
    return {**state, "intent": intent, "query_plan": plan.to_dict(), "trace_events": events}


def _month_end(month: str) -> date:
    from datetime import timedelta
    year, m = [int(x) for x in month.split("-")]
    if m == 12:
        return date(year, 12, 31)
    return date(year, m + 1, 1) - timedelta(days=1)
