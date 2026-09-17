"""LLM Model Benchmark 汇总与 Markdown 报告。"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Sequence


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Nearest-rank percentile (P95 对小样本也保持可解释)。"""
    if not values:
        return None
    if not 0 < quantile <= 1:
        raise ValueError("quantile 必须在 (0, 1] 范围内")
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def summarize_provider(
    provider: str,
    display_name: str,
    model: str,
    results: Sequence[Mapping[str, Any]],
    status: str = "completed",
    skip_reason: str = "",
) -> Dict[str, Any]:
    """汇总某 Provider 的 Case、物理调用、Token、成本和可靠性指标。"""
    cases = list(results)
    passed = sum(bool(case.get("passed")) for case in cases)
    physical_calls = [
        dict(call)
        for case in cases
        for call in case.get("llm_calls", [])
        if call.get("is_model_call", call.get("status") != "fallback")
    ]
    latencies = [float(case.get("latency_ms", 0)) for case in cases]
    input_tokens = sum(int(call["input_tokens"]) for call in physical_calls if call.get("input_tokens") is not None)
    output_tokens = sum(int(call["output_tokens"]) for call in physical_calls if call.get("output_tokens") is not None)
    known_total_tokens = [int(call["total_tokens"]) for call in physical_calls if call.get("total_tokens") is not None]
    priced_calls = [call for call in physical_calls if call.get("estimated_cost") is not None]
    currencies = sorted({str(call.get("cost_currency")) for call in priced_calls if call.get("cost_currency")})
    total_cost = sum(float(call["estimated_cost"]) for call in priced_calls)
    error_calls = [call for call in physical_calls if not call.get("success", call.get("status") == "success")]
    fallback_events = [
        call for case in cases for call in case.get("llm_calls", [])
        if call.get("fallback_used") or call.get("status") == "fallback"
    ]
    usage_sources: Dict[str, int] = {}
    for call in physical_calls:
        source = str(call.get("usage_source") or "unknown")
        usage_sources[source] = usage_sources.get(source, 0) + 1

    return {
        "provider": provider,
        "provider_display_name": display_name,
        "model": model,
        "status": status,
        "skip_reason": skip_reason,
        "golden_cases": len(cases),
        "passed": passed,
        "failed": len(cases) - passed,
        "success_rate": passed / len(cases) if cases else None,
        "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        "p95_latency_ms": percentile(latencies, 0.95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": sum(known_total_tokens),
        "total_tokens_known_calls": len(known_total_tokens),
        "average_tokens_per_case": (sum(known_total_tokens) / len(cases)) if cases else None,
        "llm_calls": len(physical_calls),
        "successful_llm_calls": sum(bool(call.get("success")) for call in physical_calls),
        "errors": len(error_calls),
        "error_rate": len(error_calls) / len(physical_calls) if physical_calls else None,
        "fallback_calls": len(fallback_events),
        "failed_cases": len(cases) - passed,
        "estimated_cost": round(total_cost, 9) if priced_calls else None,
        "estimated_cost_currency": currencies[0] if len(currencies) == 1 else ("mixed" if currencies else None),
        "estimated_cost_complete": bool(physical_calls) and len(priced_calls) == len(physical_calls),
        "unpriced_calls": len(physical_calls) - len(priced_calls),
        "usage_sources": usage_sources,
        "results": cases,
    }


def build_benchmark_report(
    dataset_version: str,
    dataset_cases: int,
    runs: int,
    models: Sequence[Mapping[str, Any]],
    data_source: str,
    generated_at: str | None = None,
) -> Dict[str, Any]:
    """构造 JSON 可序列化的统一报告对象。"""
    return {
        "report": "Model Benchmark",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"version": dataset_version, "cases_per_run": dataset_cases},
        "runs": runs,
        "data_source": data_source,
        "cost_note": (
            "Cost 为按 Provider 官方公开价格及 Token Usage 计算的估算值，并非云平台账单；"
            "不同币种不进行外汇换算，未计价调用单独标记。"
        ),
        "latency_note": "Average / P95 为完整 Agent Case 的端到端耗时；LLM Call latency 单独记录于逐调用明细。",
        "models": [dict(model) for model in models],
        "conclusion": comparison_conclusion(models),
    }


def comparison_conclusion(models: Sequence[Mapping[str, Any]]) -> str:
    """只依据已完成的真实汇总结果形成简短、克制的比较。"""
    completed = [model for model in models if model.get("status") == "completed"]
    if len(completed) < 2:
        return "至少需要两个 Provider 完成评测，才能进行模型间比较。"
    left, right = completed[0], completed[1]
    left_label = "%s (%s)" % (left.get("provider_display_name"), left.get("model"))
    right_label = "%s (%s)" % (right.get("provider_display_name"), right.get("model"))
    observations: List[str] = []
    left_rate, right_rate = left.get("success_rate"), right.get("success_rate")
    if left_rate is not None and right_rate is not None:
        if left_rate > right_rate:
            observations.append("%s 成功率较高（%.1f%% vs %.1f%%）" % (left_label, left_rate * 100, right_rate * 100))
        elif right_rate > left_rate:
            observations.append("%s 成功率较高（%.1f%% vs %.1f%%）" % (right_label, right_rate * 100, left_rate * 100))
        else:
            observations.append("两者成功率相同（%.1f%%）" % (left_rate * 100))
    left_latency, right_latency = left.get("average_latency_ms"), right.get("average_latency_ms")
    if left_latency and right_latency:
        faster, slower = (left_label, right_label) if left_latency < right_latency else (right_label, left_label)
        fast_latency, slow_latency = sorted((left_latency, right_latency))
        if fast_latency > 0:
            observations.append("%s 平均端到端延迟较低；%s 高约 %.1f%%" % (
                faster, slower, (slow_latency / fast_latency - 1) * 100,
            ))
    left_currency, right_currency = left.get("estimated_cost_currency"), right.get("estimated_cost_currency")
    left_cost, right_cost = left.get("estimated_cost"), right.get("estimated_cost")
    if left_cost is not None and right_cost is not None:
        if left_currency == right_currency:
            cheaper, cheaper_cost = (left_label, left_cost) if left_cost < right_cost else (right_label, right_cost)
            observations.append("当前样本估算成本较低的是 %s（%.6g %s）" % (cheaper, cheaper_cost, left_currency))
        else:
            observations.append("成本分别以 %s 与 %s 计价，未换汇，不能据此直接判断谁更便宜" % (
                left_currency or "未知币种", right_currency or "未知币种",
            ))
    return "；".join(observations) + "。" if observations else "可用的共同指标不足，暂不生成优劣结论。"


def render_markdown(report: Mapping[str, Any]) -> str:
    """渲染适用于作品集展示的 Benchmark Markdown。"""
    dataset = report.get("dataset", {})
    lines = [
        "# Model Benchmark",
        "",
        "## Environment",
        "",
        "- Generated at (UTC): %s" % report.get("generated_at", "unknown"),
        "- Dataset: Golden Dataset v%s, %s cases per run" % (
            dataset.get("version", "unknown"), dataset.get("cases_per_run", "unknown"),
        ),
        "- Runs per provider: %s" % report.get("runs", "unknown"),
        "- Data source: %s" % report.get("data_source", "unknown"),
        "- Latency: %s" % report.get("latency_note", ""),
        "- Cost: %s" % report.get("cost_note", ""),
        "",
        "## Overall Results",
        "",
        "| Provider / Model | Status | Golden Cases | Passed | Failed | Success Rate | Avg Latency | P95 | Input Tokens | Output Tokens | Total Tokens | Avg Tokens / Case | Est. Cost | Cost / Case | LLM Calls |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in report.get("models", []):
        label = "%s / %s" % (model.get("provider_display_name", model.get("provider")), model.get("model") or "—")
        status = model.get("status", "unknown")
        if status != "completed":
            lines.append("| %s | %s: %s | — | — | — | — | — | — | — | — | — | — | — | — | — |" % (
                label, status, _cell(model.get("skip_reason", "")),
            ))
            continue
        cost = _format_cost(model.get("estimated_cost"), model.get("estimated_cost_currency"))
        cost_per_case = None
        if model.get("estimated_cost") is not None and model.get("golden_cases"):
            cost_per_case = model["estimated_cost"] / model["golden_cases"]
        if not model.get("estimated_cost_complete") and model.get("estimated_cost") is not None:
            cost += "*"
        lines.append("| %s | %s | %d | %d | %d | %s | %s | %s | %d | %d | %d | %s | %s | %s | %d |" % (
            _cell(label), status, model.get("golden_cases", 0), model.get("passed", 0), model.get("failed", 0),
            _rate(model.get("success_rate")), _ms(model.get("average_latency_ms")), _ms(model.get("p95_latency_ms")),
            model.get("input_tokens", 0), model.get("output_tokens", 0), model.get("total_tokens", 0),
            _number(model.get("average_tokens_per_case")), cost,
            _format_cost(cost_per_case, model.get("estimated_cost_currency")), model.get("llm_calls", 0),
        ))
    lines.extend([
        "",
        "## Reliability",
        "",
        "| Provider / Model | Failed Model Calls | Error Rate | Fallback Events | Failed Cases | Unpriced Calls | Usage Sources |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for model in report.get("models", []):
        label = "%s / %s" % (model.get("provider_display_name", model.get("provider")), model.get("model") or "—")
        if model.get("status") != "completed":
            lines.append("| %s | — | — | — | — | — | — |" % _cell(label))
            continue
        sources = ", ".join("%s: %s" % (key, value) for key, value in sorted(model.get("usage_sources", {}).items())) or "none"
        lines.append("| %s | %d | %s | %d | %d | %d | %s |" % (
            _cell(label), model.get("errors", 0), _rate(model.get("error_rate")),
            model.get("fallback_calls", 0), model.get("failed_cases", 0),
            model.get("unpriced_calls", 0), _cell(sources),
        ))
    lines.extend(["", "## Conclusion", "", str(report.get("conclusion", "")), "", "## Failed Cases", ""])
    failures = [
        (model, case)
        for model in report.get("models", []) if model.get("status") == "completed"
        for case in model.get("results", []) if not case.get("passed")
    ]
    if not failures:
        lines.append("No failed cases.")
    else:
        for model, case in failures:
            expected = json.dumps(case.get("expected", {}), ensure_ascii=False, sort_keys=True)
            actual = json.dumps(case.get("actual", {}), ensure_ascii=False, sort_keys=True)
            errors = "; ".join(_safe_text(str(error)) for error in case.get("errors", [])) or "unspecified"
            lines.append(
                "- `%s` — %s / `%s`; stage: `%s`; expected: `%s`; actual: `%s`; error: %s" % (
                    _cell(str(case.get("case_id", "unknown"))),
                    _cell(str(model.get("provider_display_name", model.get("provider")))),
                    _cell(str(model.get("model", "unknown"))),
                    _cell(str(case.get("failure_stage") or "unknown")),
                    _safe_text(expected), _safe_text(actual), errors,
                )
            )
    lines.extend([
        "",
        "## Methodology",
        "",
        "Both providers use the same Golden Dataset, Agent graph, prompts, tools, semantic layer, policies, and selected data source. Retries count as separate physical model calls. Token usage is marked by source (`provider`, `estimated`, `mixed`, or `unavailable`).",
        "",
        "* Cost is estimated from configured public list prices and observed/estimated Token Usage; it is not a provider invoice. Currency differences are not normalized. `*` means at least one call has no cost estimate.",
        "",
    ])
    return "\n".join(lines)


def _safe_text(value: str) -> str:
    value = re.sub(r"(?i)(api[_ -]?key|authorization|password|secret|token)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", value)
    value = re.sub(r"(postgres(?:ql)?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value, flags=re.IGNORECASE)
    return value.replace("\n", " ").replace("|", "\\|")


def _cell(value: str) -> str:
    return _safe_text(value)


def _number(value: Any) -> str:
    return "—" if value is None else "%.1f" % float(value)


def _ms(value: Any) -> str:
    return "—" if value is None else "%.0f ms" % float(value)


def _rate(value: Any) -> str:
    return "—" if value is None else "%.1f%%" % (float(value) * 100)


def _format_cost(value: Any, currency: Any) -> str:
    if value is None:
        return "—"
    return "%.6g %s" % (float(value), currency or "currency unknown")
