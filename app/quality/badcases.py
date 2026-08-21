"""Badcase 生命周期管理：发现 → 分类 → Root Cause → Fix → Regression Case → Resolved。

扩展原有简单 badcase 记录，增加状态流转与回归关联。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class BadcaseManager:
    """管理 Badcase 的完整生命周期。"""

    def __init__(self, root: Path) -> None:
        self.directory = root / "data" / "runtime"
        self.badcase_path = self.directory / "badcases.jsonl"

    def create(
        self,
        event_id: str,
        question: str,
        category: str,
        reason: str,
        expected: str = "",
        actual: str = "",
        root_cause: str = "",
        fix: str = "",
        regression_case_id: str = "",
    ) -> str:
        """创建一条 Badcase 记录。"""
        badcase_id = "bc_" + uuid.uuid4().hex[:12]
        payload: Dict[str, Any] = {
            "badcase_id": badcase_id,
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "category": category,
            "reason": reason,
            "expected": expected,
            "actual": actual,
            "root_cause": root_cause,
            "fix": fix,
            "fixed_version": "",
            "regression_case_id": regression_case_id,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
        }
        self._append(payload)
        return badcase_id

    def resolve(self, badcase_id: str, root_cause: str, fix: str,
                regression_case_id: str = "", fixed_version: str = "") -> bool:
        """标记 Badcase 已解决。"""
        records = self.list_all()
        found = False
        for rec in records:
            if rec.get("badcase_id") == badcase_id:
                rec["status"] = "resolved"
                rec["root_cause"] = root_cause
                rec["fix"] = fix
                rec["regression_case_id"] = regression_case_id
                rec["fixed_version"] = fixed_version
                rec["resolved_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break
        if found:
            self._rewrite(records)
        return found

    def list_all(self) -> List[Dict[str, Any]]:
        if not self.badcase_path.exists():
            return []
        records = []
        for line in self.badcase_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def list_open(self) -> List[Dict[str, Any]]:
        return [r for r in self.list_all() if r.get("status") == "open"]

    def list_resolved(self) -> List[Dict[str, Any]]:
        return [r for r in self.list_all() if r.get("status") == "resolved"]

    def _append(self, payload: Dict[str, Any]) -> None:
        self.badcase_path.parent.mkdir(parents=True, exist_ok=True)
        with self.badcase_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _rewrite(self, records: List[Dict[str, Any]]) -> None:
        self.badcase_path.parent.mkdir(parents=True, exist_ok=True)
        with self.badcase_path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Demo Badcase：一个完整的 发现 → 定位 → 修复 → 回归 闭环
# ---------------------------------------------------------------------------

DEMO_BADCASE = {
    "badcase_id": "bc_demo_001",
    "event_id": "demo_event",
    "question": "各区域营业额",
    "category": "expression",
    "reason": "用户使用同义词'营业额'提问，早期版本确定性 NLQ 无法识别，返回 unsupported",
    "expected": "应识别为 sales_amount 指标并按 region_name 分组返回 4 条",
    "actual": "返回 unsupported，提示'暂未识别指标'",
    "root_cause": "metrics.json 的 sales_amount synonyms 未包含'营业额'",
    "fix": "在 metrics.json 的 sales_amount.synonyms 中添加'营业额'",
    "fixed_version": "v2.0",
    "regression_case_id": "g009",
    "status": "resolved",
    "created_at": "2025-08-01T00:00:00Z",
    "resolved_at": "2025-08-06T00:00:00Z",
}


REAL_LLM_BADCASE = {
    "badcase_id": "bc_llm_001",
    "event_id": "llm_evaluation_2026-08-19",
    "timestamp": "2026-08-19T09:33:48Z",
    "question": "过去3个月各区域销售额趋势",
    "category": "relative_time",
    "reason": "真实 LLM 评测 g016 返回 24 行，Ground Truth 期望 12 行",
    "expected": "按当前月及前两个月的 3 个完整自然月返回 12 个区域月度结果",
    "actual": "评测报告记录 row_count=24 expected=12",
    "root_cause": "LLM 计划中的 start_date/end_date 未经过统一相对时间策略归一化，模型日期可多包含一个月",
    "fix": "新增 deterministic relative-time policy；对过去/最近/近 N 个月统一按包含当前月的 N 个自然月解析，并在 LLM 计划校验时覆盖模型日期",
    "fixed_version": "relative-time-policy",
    "regression_case_id": "g016",
    "status": "resolved",
    "created_at": "2026-08-19T09:33:48Z",
    "resolved_at": "2026-08-20T00:00:00Z",
}


KNOWN_BADCASES = (DEMO_BADCASE, REAL_LLM_BADCASE)


def seed_demo_badcase(root: Path) -> str:
    """写入 demo badcase 记录（如果不存在）。"""
    manager = BadcaseManager(root)
    existing = manager.list_all()
    if any(r.get("badcase_id") == "bc_demo_001" for r in existing):
        return "bc_demo_001"
    manager._append(DEMO_BADCASE)
    return "bc_demo_001"


def seed_known_badcases(root: Path) -> List[str]:
    """将已完成 RCA 的 Badcase 证据写入当前运行时 JSONL（幂等）。"""
    manager = BadcaseManager(root)
    existing = {record.get("badcase_id") for record in manager.list_all()}
    seeded: List[str] = []
    for badcase in KNOWN_BADCASES:
        badcase_id = str(badcase["badcase_id"])
        if badcase_id not in existing:
            manager._append(dict(badcase))
        seeded.append(badcase_id)
    return seeded
