"""generate_answer 节点：将结构化事实转为用户可读回答。

模型只能基于已提供的结构化事实生成总结，不允许添加数据中不存在的数字。
LLM 不可用时使用模板化 fallback。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from app.agent.state import AgentState
from app.presentation.decision_support import build_attribution_summary


def generate_answer(state: AgentState) -> AgentState:
    root = Path(state.get("_root", "."))  # type: ignore[arg-type]
    trace_id = state.get("trace_id", "")
    started = time.monotonic()
    result = state.get("result") or {}
    intent = state.get("intent", "")
    question = state.get("question", "")
    use_llm = state.get("_use_llm", False)  # type: ignore[assignment]

    events = list(state.get("trace_events", []))

    # 先生成确定性模板回答（保证可审计、零幻觉）
    template_answer = _template_answer(intent, result, question)

    answer = template_answer
    llm_calls = list(state.get("llm_calls", []))

    # 可选 LLM 润色：仅基于已提供的事实，不添加新数字
    if use_llm and _llm_available(root):
        try:
            llm_answer = _llm_summarize(root, intent, result, question, template_answer)
            if llm_answer:
                answer = llm_answer
                llm_calls.append({
                    "provider": "deepseek", "node": "generate_answer",
                    "status": "success", "prompt_version": "v1",
                })
        except Exception as exc:  # noqa: BLE001
            llm_calls.append({
                "provider": "deepseek", "node": "generate_answer",
                "status": "fallback", "error": str(exc),
            })
            # LLM 失败时使用模板回答

    events.append({
        "trace_id": trace_id, "node": "generate_answer",
        "start_at": started, "end_at": time.monotonic(),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "status": "success", "used_llm": use_llm and len(llm_calls) > 0,
    })

    return {**state, "answer": answer, "trace_events": events, "llm_calls": llm_calls}


def _llm_available(root: Path) -> bool:
    import os
    from app.llm.deepseek_client import load_env_file
    load_env_file(root / ".env")
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


def _llm_summarize(root: Path, intent: str, result: Dict[str, Any],
                   question: str, template: str) -> str:
    """使用 DeepSeek 基于已提供的事实生成总结。"""
    from app.llm.deepseek_client import DeepSeekClient, DeepSeekConfig
    import json
    client = DeepSeekClient(DeepSeekConfig.from_env(root))
    system_prompt = (
        "你是零售经营分析 Data Agent 的回答生成器。\n"
        "只能基于用户提供的已验证 JSON 事实生成中文总结，"
        "不允许添加数据中不存在的数字和业务事实。\n"
        "如果数据为空或不足，明确说明，不编造。\n"
        "归因结论只能表述为数据贡献因素，不能声称已证明因果。\n"
        "只返回自然语言总结，不要返回 JSON 或代码块。"
    )
    facts = json.dumps({"intent": intent, "question": question, "result": _safe_result(result)},
                       ensure_ascii=False, default=str)
    return client.complete_text(system_prompt, facts, max_tokens=600)


def _safe_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """剔除 result 中不适合给 LLM 的大字段（如 sql），保留事实。"""
    safe = {}
    for key in ("skill", "metric", "metric_display_name", "metric_definition",
                "rows", "time_range", "comparison", "row_count", "scope",
                "current_period", "comparison_period", "current_total",
                "comparison_total", "total_delta", "dimension", "contributions",
                "top_negative", "limitations", "anomalies", "anomaly_count",
                "has_anomaly", "period", "kpis", "markdown",
                "trend_points", "first_value", "last_value", "overall_change_rate"):
        if key in result:
            safe[key] = result[key]
    return safe


def _template_answer(intent: str, result: Dict[str, Any], question: str) -> str:
    """确定性模板回答，零幻觉。"""
    if intent == "metric_query":
        return _answer_metric_query(result, question)
    if intent == "trend_analysis":
        return _answer_trend(result, question)
    if intent == "anomaly_analysis":
        return _answer_anomaly(result, question)
    if intent == "attribution_analysis":
        return _answer_attribution(result, question)
    if intent == "report_generation":
        return _answer_report(result, question)
    return "已处理您的请求。"


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, float):
        return "%.2f" % v
    return str(v)


def _fmt_rate(v: Any) -> str:
    if v is None:
        return "N/A"
    return "%.2f%%" % (float(v) * 100)


def _fmt_currency(v: Any) -> str:
    if v is None:
        return "N/A"
    return "¥%s" % format(float(v), ",.2f")


def _answer_metric_query(result: Dict[str, Any], question: str) -> str:
    display = result.get("metric_display_name", result.get("metric", ""))
    rows = result.get("rows", [])
    if not rows:
        return "%s查询完成，但未返回数据。请检查筛选条件或时间范围。" % display
    parts = ["%s查询结果（共 %d 条）：" % (display, len(rows))]
    for row in rows[:10]:
        dims = {k: v for k, v in row.items() if k not in ("current_value", "comparison_value", "change", "change_rate", "value")}
        dim_str = "、".join("%s=%s" % (k, v) for k, v in dims.items()) if dims else "整体"
        if "current_value" in row:
            parts.append("  %s：当前 %s，对比 %s，变化 %s（%s）" % (
                dim_str, _fmt(row.get("current_value")), _fmt(row.get("comparison_value")),
                _fmt(row.get("change")), _fmt_rate(row.get("change_rate"))))
        elif "value" in row:
            parts.append("  %s：%s" % (dim_str, _fmt(row.get("value"))))
    if len(rows) > 10:
        parts.append("  ...（共 %d 条，仅展示前 10 条）" % len(rows))
    return "\n".join(parts)


def _answer_trend(result: Dict[str, Any], question: str) -> str:
    display = result.get("metric_display_name", result.get("metric", ""))
    rows = result.get("rows", [])
    if not rows:
        return "%s趋势查询完成，但未返回数据。" % display
    parts = ["%s趋势（%d 个时间点）：" % (display, len(rows))]
    for row in rows[:12]:
        period = row.get("month_start") or row.get("week_start") or row.get("sale_date") or ""
        parts.append("  %s：%s" % (period, _fmt(row.get("value"))))
    overall = result.get("overall_change_rate")
    if overall is not None:
        direction = "增长" if overall >= 0 else "下降"
        parts.append("整体%s %s" % (direction, _fmt_rate(abs(overall))))
    return "\n".join(parts)


def _answer_anomaly(result: Dict[str, Any], question: str) -> str:
    anomalies = result.get("anomalies", [])
    if not anomalies:
        return "%s 期间未检测到超过规则阈值的销售异常。" % result.get("month", "")
    parts = ["%s 期间检测到 %d 项销售异常：" % (result.get("month", ""), len(anomalies))]
    for a in anomalies[:5]:
        parts.append("  [%s] %s：当前销售额 %s，基线 %s，变化率 %s" % (
            a.get("severity", "").upper(), a.get("entity_name", ""),
            _fmt(a.get("current_value")), _fmt(a.get("baseline_value")),
            _fmt_rate(a.get("change_rate"))))
    return "\n".join(parts)


def _answer_attribution(result: Dict[str, Any], question: str) -> str:
    summary = build_attribution_summary(result)
    change_rate = summary.get("change_rate")
    delta = summary.get("total_delta", 0.0)
    direction = summary.get("direction", "变化")
    if change_rate is None:
        parts = ["结论：%s %s 销售额为 %s，较 %s %s %s。" % (
            summary.get("scope", "当前范围"),
            summary.get("current_period", ""),
            _fmt_currency(summary.get("current_total")),
            summary.get("comparison_period", ""),
            direction,
            _fmt_currency(abs(delta)),
        )]
    else:
        parts = ["结论：%s %s 销售额为 %s，较 %s %s %s（%s）。" % (
            summary.get("scope", "当前范围"),
            summary.get("current_period", ""),
            _fmt_currency(summary.get("current_total")),
            summary.get("comparison_period", ""),
            direction,
            _fmt_currency(abs(delta)),
            _fmt_rate(change_rate),
        )]
    top_neg = summary.get("top_negative", [])
    if top_neg:
        parts.append("主要下降贡献（数据贡献，不等同于已验证的业务因果）：")
        for c in top_neg[:5]:
            parts.append("  %s：下降 %s，贡献 %s" % (
                c.get("member", ""), _fmt_currency(abs(c.get("delta", 0))),
                _fmt_rate(c.get("contribution_rate"))))
    parts.append(result.get("limitations", "建议结合订单数、客单价、客流、库存和促销数据进一步核查。"))
    return "\n".join(parts)


def _answer_report(result: Dict[str, Any], question: str) -> str:
    period = result.get("period", "")
    scope = result.get("scope", "")
    kpi_count = len(result.get("kpis", []))
    anomaly_count = result.get("anomaly_count", 0)
    return "已生成 %s %s 经营分析月报（%d 个 KPI，%d 项异常）。完整报告见 markdown 字段。" % (
        period, scope, kpi_count, anomaly_count)
