"""LLM E2E Evaluation：在有 API Key 时运行 LLM 增强链路评测。

运行模式说明：
- mode=deterministic：由 scripts/run_evaluation.py 生成，不调用 LLM。
- mode=llm：本脚本生成，真实调用 LLM 解析问题并构建 Query Plan。

无 API Key 或未配置固定评测模型时明确 skip，并删除可能残留的旧报告，避免误导：
不要出现 "100% pass 但 0 LLM calls" 的无证据报告。

真实 LLM E2E 使用已部署的 Supabase PostgreSQL 数据源，确保查询计划、权限、
语义层和受控 SQL 在公网近生产数据源上一起验证；确定性回归仍固定使用 DuckDB。

报告至少包含：model / cases / passed / plan_accuracy / llm_calls /
fallback_count / fallback_case_count / fallback_rate，且按用例预期行为判定 PASS。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.graph import run_agent
from app.config import DataSourceConfig
from app.data_sources.base import DataSourceBase
from app.data_sources.factory import create_data_source
from app.config import load_env_file
from app.llm.siliconflow_client import ModelConfig
from app.quality.evaluation import _load_cases
from app.quality.llm_evaluation import check_case, check_ground_truth

REPORT_PATH = ROOT / "reports" / "llm_evaluation_report.json"


def _llm_entries(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """state 中的 llm_calls 记录。"""
    return list(state.get("llm_calls", []))


def _count_model_calls(entries: List[Dict[str, Any]]) -> int:
    """统计真实物理模型请求；一次重试也单独计数。"""
    return sum(1 for entry in entries if entry.get("is_model_call", entry.get("status") != "fallback"))


def _count_fallbacks(entries: List[Dict[str, Any]]) -> int:
    """统计跨 Provider 或确定性 fallback 的次数。"""
    return sum(1 for e in entries if (
        e.get("status") == "fallback"
        or e.get("fallback_used")
        or e.get("provider_fallback_used")
    ))


def _delete_stale_report() -> None:
    """无 Key 运行时删除旧报告，避免误导性 '0 LLM calls / 100% pass' 残留。"""
    if REPORT_PATH.exists():
        REPORT_PATH.unlink()
        print(f"已删除过期 LLM 报告（避免 '0 LLM calls / 100% pass' 误导）: {REPORT_PATH}")


def _create_evaluation_source() -> DataSourceBase:
    """创建真实 LLM E2E 的 Supabase PostgreSQL 数据源。

    LLM E2E 的目的之一是验证公网近生产链路，因此不能在 DATA_SOURCE=duckdb
    时悄悄降级。确定性 Golden Regression 才使用 DuckDB 作为离线基线。
    """
    config = DataSourceConfig.from_env(ROOT)
    if config.kind != "postgresql":
        raise RuntimeError(
            "LLM E2E 评测要求 DATA_SOURCE=postgresql（Supabase）；"
            "确定性回归请运行 python3 scripts/run_evaluation.py"
        )
    return create_data_source(ROOT, config)


def main() -> int:
    load_env_file(ROOT / ".env")
    if not ModelConfig.is_configured(ROOT, mode="evaluation"):
        _delete_stale_report()
        print("SKIP: 未配置当前 Provider 的 API Key 或固定评测模型，LLM E2E 评测跳过（不会生成报告）。")
        print("确定性 baseline 评测请运行: python3 scripts/run_evaluation.py")
        return 0

    config = ModelConfig.from_env(ROOT, mode="evaluation")
    model = config.model
    cases = _load_cases(ROOT)
    try:
        evaluation_source = _create_evaluation_source()
        if not evaluation_source.health_check():
            raise RuntimeError("Supabase PostgreSQL 健康检查失败")
    except Exception as exc:  # noqa: BLE001
        _delete_stale_report()
        print("SKIP: %s（不会生成 LLM 报告）。" % exc)
        return 0
    print("Running LLM E2E evaluation on %d cases (model=%s)..." % (len(cases), model))

    results: List[Dict[str, Any]] = []
    total_llm_calls = 0
    total_fallbacks = 0
    fallback_cases = 0
    total_latency = 0.0
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    successful_llm_calls = 0
    error_calls = 0
    cost_values: List[float] = []
    unpriced_calls = 0
    usage_sources: Dict[str, int] = {}
    plan_correct = 0
    executable_cases = 0
    exec_success = 0

    for case in cases:
        question = case["question"]
        start = time.monotonic()
        state = run_agent(
            question, ROOT,
            user_id=case.get("user_id", "user_hq"),
            role=case.get("role", "hq_manager"),
            data_scope=case.get("data_scope", {"scope": "all"}),
            use_llm=True, llm_mode="evaluation", data_source=evaluation_source,
        )
        latency = time.monotonic() - start
        total_latency += latency

        entries = _llm_entries(state)
        physical_calls = [
            entry for entry in entries
            if entry.get("is_model_call", entry.get("status") != "fallback")
        ]
        llm_calls = len(physical_calls)
        fallback = _count_fallbacks(entries)
        total_llm_calls += llm_calls
        successful_llm_calls += sum(bool(entry.get("success", entry.get("status") == "success")) for entry in physical_calls)
        error_calls += sum(not bool(entry.get("success", entry.get("status") == "success")) for entry in physical_calls)
        total_fallbacks += fallback
        if fallback:
            fallback_cases += 1
        for entry in physical_calls:
            input_tokens += int(entry.get("input_tokens") or 0)
            output_tokens += int(entry.get("output_tokens") or 0)
            if entry.get("total_tokens") is not None:
                total_tokens += int(entry["total_tokens"])
            source_name = str(entry.get("usage_source") or "unknown")
            usage_sources[source_name] = usage_sources.get(source_name, 0) + 1
            if entry.get("estimated_cost") is None:
                unpriced_calls += 1
            else:
                cost_values.append(float(entry["estimated_cost"]))

        intent_ok = state.get("intent") == case.get("intent")
        if case.get("baseline_only") or case.get("intent") == "trend_analysis":
            intent_ok = state.get("intent") in ("metric_query", "trend_analysis")
        if intent_ok:
            plan_correct += 1

        passed, case_errors = check_case(state, case)
        gt_ok, gt_error = check_ground_truth(state, case)
        if passed and not gt_ok:
            passed = False
            case_errors.append("ground_truth mismatch: %s" % gt_error)

        executable = not (case.get("should_reject") or case.get("should_deny"))
        if executable:
            executable_cases += 1
            result = state.get("result") or {}
            if passed and (bool(result.get("success")) or case.get("expect_empty")):
                exec_success += 1

        results.append({
            "case_id": case["id"], "question": question, "category": case.get("category"),
            "passed": passed, "intent": state.get("intent"),
            "permission_decision": state.get("permission_decision"),
            "latency_ms": int(latency * 1000),
            "llm_calls": llm_calls,
            "successful_llm_calls": sum(bool(entry.get("success", entry.get("status") == "success")) for entry in physical_calls),
            "error_calls": sum(not bool(entry.get("success", entry.get("status") == "success")) for entry in physical_calls),
            "fallback": fallback > 0,
            "llm_providers": [entry.get("provider") for entry in entries if entry.get("provider")],
            "llm_roles": [entry.get("role") for entry in entries if entry.get("role")],
            "primary_provider": config.provider,
            "primary_role": "main",
            "primary_model": config.model,
            "actual_provider": next((entry.get("provider") for entry in reversed(entries) if entry.get("provider")), config.provider),
            "actual_role": next((entry.get("role") for entry in reversed(entries) if entry.get("role")), "main"),
            "actual_model": next((entry.get("model") for entry in reversed(entries) if entry.get("model")), config.model),
            "fallback_events": [
                {
                    "provider": entry.get("provider"),
                    "role": entry.get("role"),
                    "fallback_from_model": entry.get("fallback_from_model") or entry.get("fallback_from"),
                    "fallback_model": entry.get("provider_fallback_model") or entry.get("fallback_model"),
                    "fallback_reason": entry.get("fallback_reason"),
                }
                for entry in entries
                if entry.get("fallback_used") or entry.get("provider_fallback_used")
            ],
            "error_type": state.get("error_type"),
            "errors": case_errors,
        })
        print("[%s] %s (intent=%s, llm_calls=%d, fallback=%s, %.1fs)" % (
            "PASS" if passed else "FAIL", case["id"], state.get("intent"),
            llm_calls, fallback > 0, latency))

    passed = sum(1 for r in results if r["passed"])
    fallback_rate = fallback_cases / len(results) if results else 0
    print("\nLLM E2E Result: %d/%d passed" % (passed, len(results)))
    print("Model: %s" % model)
    print("Total physical LLM calls: %d (success=%d, errors=%d)" % (
        total_llm_calls, successful_llm_calls, error_calls,
    ))
    print("Fallback count: %d (rate=%.2f)" % (total_fallbacks, fallback_rate))
    print("Total latency: %.1fs" % total_latency)
    failed = [r for r in results if not r["passed"]]
    if failed:
        print("Failed cases:")
        for r in failed:
            print("  [%s] %s -> %s" % (r["case_id"], r["question"], "; ".join(r["errors"])))

    report: Dict[str, Any] = {
        "mode": "llm",
        "provider": config.provider,
        "primary_provider": config.provider,
        "model": model,
        "model_roles": ["router", "main", "reason", "vision"],
        "data_source": "postgresql",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluation_timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "LLM-enabled evaluation：真实调用 LLM 构建 Query Plan；"
                "相对时间窗口由 deterministic relative-time policy 统一归一化。",
        "total": len(results), "passed": passed,
        "case_count": len(results), "pass_count": passed,
        "pass_rate": passed / len(results) if results else 0,
        "overall_pass_rate": passed / len(results) if results else 0,
        "plan_accuracy": plan_correct / len(results) if results else 0,
        "executable_cases": executable_cases,
        "non_executable_cases": len(results) - executable_cases,
        "executable_success_rate": exec_success / executable_cases if executable_cases else None,
        "total_llm_calls": total_llm_calls,
        "llm_calls": total_llm_calls,
        "fallback_count": total_fallbacks,
        "fallback_case_count": fallback_cases,
        "fallback_rate": fallback_rate,
        "actual_providers": sorted({provider for item in results for provider in item.get("llm_providers", []) if provider}),
        "total_latency_s": total_latency,
        "latency_ms": int(total_latency * 1000),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "successful_llm_calls": successful_llm_calls,
        "error_calls": error_calls,
        "error_rate": error_calls / total_llm_calls if total_llm_calls else None,
        "usage_sources": usage_sources,
        "estimated_cost": round(sum(cost_values), 9) if cost_values else None,
        "estimated_cost_currency": next((
            entry.get("cost_currency") for item in results for entry in _llm_entries(item)
            if entry.get("estimated_cost") is not None
        ), None),
        "estimated_cost_complete": bool(total_llm_calls) and unpriced_calls == 0,
        "unpriced_calls": unpriced_calls,
        "results": results,
    }
    evaluation_source.close()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report written to: %s" % REPORT_PATH)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
