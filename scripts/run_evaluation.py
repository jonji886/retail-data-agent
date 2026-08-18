"""运行 Golden Dataset 评测（Evaluation 2.0）。"""

from __future__ import annotations

import json
import sys
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

    # v2 详细报告
    print("\n--- Evaluation 2.0 ---")
    report = run_golden_v2(ROOT)
    print("Total cases: %d" % report["total"])
    print("Overall pass rate: %.1f%%" % (report["overall_pass_rate"] * 100))
    print("Plan accuracy: %.1f%%" % (report["plan_accuracy"] * 100))
    print("Execution success rate: %.1f%%" % (report["execution_success_rate"] * 100))
    if report["result_accuracy"] is not None:
        print("Result accuracy: %.1f%%" % (report["result_accuracy"] * 100))
    if report["unsupported_reject_rate"] is not None:
        print("Unsupported reject rate: %.1f%%" % (report["unsupported_reject_rate"] * 100))
    if report["permission_safety_pass_rate"] is not None:
        print("Permission safety pass rate: %.1f%%" % (report["permission_safety_pass_rate"] * 100))

    # 写入报告文件
    report_dir = ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nReport written to: %s" % report_path)

    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
