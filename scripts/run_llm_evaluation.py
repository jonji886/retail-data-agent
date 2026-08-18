"""LLM E2E Evaluation：在有 API Key 时运行 LLM 增强链路评测。

无 API Key 时明确 skip，不影响测试套件。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.graph import run_agent
from app.llm.deepseek_client import load_env_file
from app.quality.evaluation import _load_cases


def main() -> None:
    load_env_file(ROOT / ".env")
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        print("SKIP: 未配置 DEEPSEEK_API_KEY，LLM E2E 评测跳过。")
        print("确定性 baseline 评测请运行: python3 scripts/run_evaluation.py")
        return

    cases = _load_cases(ROOT)
    print("Running LLM E2E evaluation on %d cases..." % len(cases))
    results = []
    total_llm_calls = 0
    total_latency = 0

    for case in cases:
        question = case["question"]
        start = time.monotonic()
        state = run_agent(
            question, ROOT,
            user_id=case.get("user_id", "user_hq"),
            role=case.get("role", "hq_manager"),
            data_scope=case.get("data_scope", {"scope": "all"}),
            use_llm=True,
        )
        latency = time.monotonic() - start
        total_latency += latency
        llm_calls = len(state.get("llm_calls", []))
        total_llm_calls += llm_calls
        passed = _check_case(state, case)
        results.append({
            "case_id": case["id"], "question": question,
            "passed": passed, "intent": state.get("intent"),
            "latency_ms": int(latency * 1000), "llm_calls": llm_calls,
            "error_type": state.get("error_type"),
        })
        print("[%s] %s (intent=%s, llm_calls=%d, %.1fs)" % (
            "PASS" if passed else "FAIL", case["id"], state.get("intent"),
            llm_calls, latency))

    passed = sum(1 for r in results if r["passed"])
    print("\nLLM E2E Result: %d/%d passed" % (passed, len(results)))
    print("Total LLM calls: %d" % total_llm_calls)
    print("Total latency: %.1fs" % total_latency)
    print("Avg LLM calls per case: %.1f" % (total_llm_calls / len(results) if results else 0))

    report = {
        "total": len(results), "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "total_llm_calls": total_llm_calls,
        "total_latency_s": total_latency,
        "results": results,
    }
    report_path = ROOT / "reports" / "llm_evaluation_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Report written to: %s" % report_path)


def _check_case(state: dict, case: dict) -> bool:
    intent = state.get("intent")
    if case.get("should_reject") and intent != "unsupported":
        return False
    if case.get("should_deny") and state.get("permission_decision") != "deny":
        return False
    if case.get("should_allow") and state.get("permission_decision") != "allow":
        return False
    # baseline_only 用例：Agent 会识别为 trend_analysis，允许 metric_query 或 trend_analysis
    if case.get("baseline_only"):
        if intent not in ("metric_query", "trend_analysis"):
            return False
    elif case.get("intent") and intent != case["intent"]:
        return False
    if state.get("error_type") and not case.get("should_reject") and not case.get("should_deny"):
        return False
    return True


if __name__ == "__main__":
    main()
