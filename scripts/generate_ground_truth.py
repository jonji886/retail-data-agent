"""生成 Golden Dataset 的 Ground Truth。

Ground Truth 由确定性 Semantic Layer（MetricCatalog + 中文 NLQ 解析）生成 SQL，
再通过只读 DuckDB 执行得到真实数值，回写到 golden_questions.json 的 ground_truth
字段。全程不调用 LLM、不人工硬编码，保证标准答案可复现、可审计。

用法：
    python3 scripts/generate_ground_truth.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.nlq import NLQError, NaturalLanguageQueryEngine

CASES_PATH = ROOT / "configs" / "evaluation" / "golden_questions.json"

# 不产生标量数值结果、需要走完整 Agent 图评测的 intent
_NON_SCALAR_INTENTS = {
    "attribution_analysis",
    "anomaly_analysis",
    "report_generation",
    "unsupported",
}


def _row_value(row: Dict[str, Any]) -> float:
    return float(row.get("value") or row.get("current_value") or 0)


def main() -> None:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    engine = NaturalLanguageQueryEngine(ROOT)
    updated = 0
    skipped: list[str] = []

    for case in data["cases"]:
        case_id = case["id"]
        # 安全/权限/归因/异常/报告类用例不生成标量 ground truth
        if case.get("should_reject") or case.get("should_deny") or case.get("should_allow"):
            skipped.append(case_id)
            continue
        if case.get("intent") in _NON_SCALAR_INTENTS:
            skipped.append(case_id)
            continue
        try:
            answer = engine.answer(case["question"])
        except NLQError as exc:
            skipped.append("%s(NLQError: %s)" % (case_id, exc))
            continue

        rows = answer.rows
        ground_truth: Dict[str, Any] = {
            "source": "semantic_layer_duckdb",
            "sql": " ".join(answer.sql.split()),
            "row_count": len(rows),
            "tolerance": 0.01,
        }
        if rows:
            # value 表示该问题的整体聚合值：单行取该行，多行取各行求和。
            ground_truth["value"] = round(sum(_row_value(r) for r in rows), 2)
        case["ground_truth"] = ground_truth
        updated += 1
        print("[OK] %-6s rows=%-3d value=%s" % (
            case_id, len(rows), ground_truth.get("value")))

    CASES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nUpdated %d cases, skipped %d: %s" % (updated, len(skipped), skipped))


if __name__ == "__main__":
    main()
