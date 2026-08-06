"""运行确定性 NLQ Golden Dataset。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.quality.evaluation import run_golden


def main() -> None:
    results = run_golden(ROOT)
    print("Running %d golden cases..." % len(results))
    for result in results:
        print("[%s] %s" % ("PASS" if result.passed else "FAIL", result.case_id))
        if not result.passed:
            print("  %s" % ", ".join(result.errors))
    passed = sum(1 for result in results if result.passed)
    print("Result: %d/%d passed" % (passed, len(results)))
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
