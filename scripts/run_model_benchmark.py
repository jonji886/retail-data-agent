"""Run the shared Golden Dataset against multiple model Providers."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.graph import run_agent
from app.config import DataSourceConfig, load_env_file
from app.data_sources.factory import create_data_source
from app.llm.providers import available_providers, resolve_provider
from app.llm.siliconflow_client import ModelConfig
from app.quality.evaluation import _load_cases
from app.quality.llm_evaluation import check_case, check_ground_truth
from app.quality.model_benchmark import build_benchmark_report, render_markdown, summarize_provider


DEFAULT_REPORT_PATH = ROOT / "reports" / "model_benchmark.md"
_SAFE_CALL_FIELDS = (
    "provider", "role", "model", "latency_ms", "input_tokens", "output_tokens",
    "total_tokens", "usage_source", "estimated_cost", "cost_currency", "success",
    "status", "error_type", "error_category", "fallback_used", "is_model_call",
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare model Providers on the same Golden Dataset")
    parser.add_argument("--providers", default="current,qwen", help="逗号分隔 Provider 名；current 指 LLM_PROVIDER")
    parser.add_argument("--runs", type=int, default=1, help="每个 Provider 重复运行次数（默认 1）")
    parser.add_argument(
        "--data-source", choices=("postgresql", "duckdb"), default="postgresql",
        help="评测数据源；默认 PostgreSQL，与现有 LLM E2E 一致；DuckDB 可用于本地离线比较",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH, help="Markdown 报告输出路径")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs 必须至少为 1")
    return args


def _resolve_names(raw_names: str) -> List[str]:
    current = resolve_provider().name
    names: List[str] = []
    for raw_name in raw_names.split(","):
        name = raw_name.strip().lower()
        if not name:
            continue
        name = current if name == "current" else name
        if name not in available_providers():
            raise ValueError("不支持 Provider %r；支持项：%s" % (name, ", ".join(available_providers())))
        if name not in names:
            names.append(name)
    if not names:
        raise ValueError("至少指定一个 Provider")
    return names


def _safe_error(value: str) -> str:
    value = re.sub(r"(?i)(api[_ -]?key|authorization|password|secret|token)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", value)
    value = re.sub(r"(postgres(?:ql)?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value, flags=re.IGNORECASE)
    return value


def _safe_call_records(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = []
    for call in state.get("llm_calls", []):
        records.append({key: call.get(key) for key in _SAFE_CALL_FIELDS if key in call})
    return records


def _expected(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: case[key]
        for key in ("intent", "metric", "dimension", "filter", "expected_filter", "should_reject", "should_deny", "should_allow")
        if key in case
    }


def _actual(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = state.get("query_plan") or {}
    result = state.get("result") or {}
    return {
        "intent": state.get("intent"),
        "query_plan": {
            key: plan[key]
            for key in ("metric", "dimensions", "filters", "start_date", "end_date", "comparison")
            if key in plan
        },
        "permission_decision": state.get("permission_decision"),
        "result_success": result.get("success"),
        "error_type": state.get("error_type"),
    }


def _failure_stage(state: Dict[str, Any], errors: List[str]) -> str | None:
    if not errors:
        return None
    if state.get("error_type"):
        return "agent_or_provider"
    if any(error.startswith("intent=") for error in errors):
        return "intent_or_query_plan"
    if any("permission" in error or "should_allow" in error or "should_deny" in error for error in errors):
        return "policy"
    if any("execution" in error or "skill failed" in error or "tool execution" in error for error in errors):
        return "skill_or_data_source"
    if any("ground_truth" in error for error in errors):
        return "result_accuracy"
    return "evaluation_expectation"


def _run_case(case: Dict[str, Any], root: Path, source: Any, run_number: int, provider: str, model: str) -> Dict[str, Any]:
    started = time.monotonic()
    state: Dict[str, Any]
    try:
        state = run_agent(
            case["question"], root,
            user_id=case.get("user_id", "user_hq"),
            role=case.get("role", "hq_manager"),
            data_scope=case.get("data_scope", {"scope": "all"}),
            use_llm=True,
            llm_mode="evaluation",
            data_source=source,
        )
    except Exception as exc:  # one broken case should not abort the remaining Golden set
        state = {
            "error_type": type(exc).__name__,
            "error_message": _safe_error(str(exc)),
            "llm_calls": [],
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    passed, errors = check_case(state, case)
    ground_truth_ok, ground_truth_error = check_ground_truth(state, case)
    if passed and not ground_truth_ok:
        passed = False
        errors.append("ground_truth mismatch: %s" % ground_truth_error)
    return {
        "case_id": case["id"],
        "run": run_number,
        "passed": passed,
        "expected": _expected(case),
        "actual": _actual(state),
        "failure_stage": _failure_stage(state, errors),
        "errors": [_safe_error(str(error)) for error in errors],
        "latency_ms": latency_ms,
        "llm_calls": _safe_call_records(state),
        "provider": provider,
        "model": model,
    }


def _provider_environment(provider: str) -> tuple[Dict[str, str | None], str]:
    spec = resolve_provider(provider)
    api_key, _ = spec.resolve_api_key()
    model = spec.role_model("main") or spec.default_main_model
    if not api_key:
        return {}, "未配置 %s" % " / ".join(spec.api_key_envs)
    if not model:
        return {}, "未配置 Main 模型"
    previous = {name: os.environ.get(name) for name in ("LLM_PROVIDER", "EVAL_LLM_MODEL")}
    os.environ["LLM_PROVIDER"] = provider
    os.environ["EVAL_LLM_MODEL"] = model
    return previous, ""


def _restore_environment(previous: Dict[str, str | None]) -> None:
    for name, value in previous.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _run_provider(provider: str, display_name: str, root: Path, cases: List[Dict[str, Any]], runs: int, source: Any) -> Dict[str, Any]:
    previous, reason = _provider_environment(provider)
    if reason:
        return summarize_provider(provider, display_name, "", [], status="skipped", skip_reason=reason)
    try:
        config = ModelConfig.from_env(root, mode="evaluation")
        print("\nProvider %s · %s · %d run(s)" % (display_name, config.model, runs), flush=True)
        results: List[Dict[str, Any]] = []
        for run_number in range(1, runs + 1):
            for case in cases:
                result = _run_case(case, root, source, run_number, provider, config.model)
                results.append(result)
                print("[%s] %s run=%d (%.1fs)" % (
                    "PASS" if result["passed"] else "FAIL", case["id"], run_number,
                    result["latency_ms"] / 1000,
                ), flush=True)
        return summarize_provider(provider, display_name, config.model, results)
    except Exception as exc:  # preserve other provider results and report configuration errors without secrets
        safe_reason = _safe_error(str(exc))
        print("SKIP %s: %s" % (display_name, safe_reason), flush=True)
        return summarize_provider(provider, display_name, "", [], status="skipped", skip_reason=safe_reason)
    finally:
        _restore_environment(previous)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    load_env_file(ROOT / ".env")
    os.environ["DATA_SOURCE"] = args.data_source
    try:
        providers = _resolve_names(args.providers)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    dataset = json.loads((ROOT / "configs" / "evaluation" / "golden_questions.json").read_text(encoding="utf-8"))
    cases = _load_cases(ROOT)

    model_results: List[Dict[str, Any]] = []
    source = None
    source_error = ""
    try:
        source_config = DataSourceConfig.from_env(ROOT)
        if source_config.kind != args.data_source:
            raise RuntimeError("数据源配置与 --data-source 不一致")
        source = create_data_source(ROOT, source_config)
        if not source.health_check():
            raise RuntimeError("PostgreSQL 健康检查失败")
    except Exception as exc:  # no database credentials or connection details are included in the report
        source_error = _safe_error(str(exc))

    for provider in providers:
        spec = resolve_provider(provider)
        if source_error:
            model_results.append(summarize_provider(
                provider, spec.display_name, "", [], status="skipped", skip_reason=source_error,
            ))
        else:
            model_results.append(_run_provider(provider, spec.display_name, ROOT, cases, args.runs, source))
    if source is not None:
        source.close()

    report = build_benchmark_report(
        dataset_version=str(dataset.get("version", "unknown")),
        dataset_cases=len(cases),
        runs=args.runs,
        models=model_results,
        data_source=args.data_source if not source_error else "unavailable",
    )
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    print("\nBenchmark report: %s" % output)
    for model in model_results:
        if model["status"] == "completed":
            print("%s: %d/%d passed, calls=%d, errors=%d, fallbacks=%d" % (
                model["provider_display_name"], model["passed"], model["golden_cases"],
                model["llm_calls"], model["errors"], model["fallback_calls"],
            ))
        else:
            print("%s: SKIP (%s)" % (model["provider_display_name"], model["skip_reason"]))
    print("Conclusion: %s" % report["conclusion"])
    if source is None or not any(model["status"] == "completed" for model in model_results):
        return 2
    return 1 if any(model.get("failed_cases", 0) for model in model_results if model["status"] == "completed") else 0


if __name__ == "__main__":
    sys.exit(main())
