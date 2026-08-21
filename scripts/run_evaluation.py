"""运行 Golden Dataset 评测（Evaluation 2.0）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.quality.evaluation import run_golden, run_golden_v2


def main() -> None:
    # v1 兼容输出
    results = run_golden(ROOT)
    print("Running %d golden cases (baseline)..." % len(results))
    for result in results:
        print("[%s] %s" % ("PASS" if result.passed else "FAIL", result.case_id))
        if not result.passed:
            print("  %s" % ", ".join(result.errors))
    passed = sum(1 for result in results if result.passed)
    print("Baseline Result: %d/%d passed" % (passed, len(results)))

    # v2 详细报告（分层指标：Plan / Execution / Result / Behavior）
    print("\n--- Evaluation 2.0 (分层指标) ---")
    report = run_golden_v2(ROOT)
    report["mode"] = "deterministic"
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print("Total cases: %d" % report["total"])
    print("[Overall]  pass rate: %.1f%%" % (report["overall_pass_rate"] * 100))
    print("[Plan]     accuracy: %.1f%%" % (report["plan_accuracy"] * 100))
    print("[Execution] executable cases: %d / non-executable: %d" % (
        report["executable_cases"], report["non_executable_cases"]))
    print("[Execution] executable success rate: %.1f%%" % (report["executable_success_rate"] * 100))
    if report["result_accuracy"] is not None:
        print("[Result]   accuracy: %.1f%%" % (report["result_accuracy"] * 100))
    if report["unsupported_reject_rate"] is not None:
        print("[Behavior] unsupported reject rate: %.1f%%" % (report["unsupported_reject_rate"] * 100))
    if report["permission_safety_pass_rate"] is not None:
        print("[Behavior] permission safety pass rate: %.1f%%" % (report["permission_safety_pass_rate"] * 100))
    if report["security_defense_rate"] is not None:
        print("[Behavior] security defense rate: %.1f%%" % (report["security_defense_rate"] * 100))
    print("\n提示：LLM 增强评测需单独运行 python3 scripts/run_llm_evaluation.py，"
          "未配置 OPENROUTER_API_KEY 时不会生成 LLM 报告（避免 0 calls / 100% 误导）。")

    # 写入报告文件
    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nReport written to: %s" % report_path)

    if passed != len(results) or report.get("passed") != report.get("total"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
