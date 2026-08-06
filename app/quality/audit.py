"""本地 JSONL 审计日志与 Badcase 记录。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditLogger:
    def __init__(self, root: Path) -> None:
        self.directory = root / "data" / "runtime"
        self.audit_path = self.directory / "audit.jsonl"
        self.badcase_path = self.directory / "badcases.jsonl"

    def record_query(
        self,
        question: str,
        mode: str,
        status: str,
        parsed: Optional[Any] = None,
        sql: Optional[str] = None,
        row_count: int = 0,
        error: Optional[str] = None,
    ) -> str:
        event_id = uuid.uuid4().hex[:12]
        payload: Dict[str, Any] = {
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "query",
            "question": question,
            "mode": mode,
            "status": status,
            "row_count": row_count,
            "error": error,
        }
        if parsed is not None:
            payload["plan"] = {
                "metric": parsed.metric.name,
                "dimensions": list(parsed.dimensions),
                "filters": dict(parsed.filters),
                "time_grain": parsed.date_range.time_grain,
                "start_date": parsed.date_range.start.isoformat(),
                "end_date": parsed.date_range.end.isoformat(),
                "comparison": parsed.comparison,
            }
        if sql:
            payload["sql"] = sql
        self._append(self.audit_path, payload)
        return event_id

    def record_badcase(self, event_id: str, question: str, reason: str, expected: str = "") -> str:
        badcase_id = uuid.uuid4().hex[:12]
        self._append(self.badcase_path, {
            "badcase_id": badcase_id,
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question": question,
            "reason": reason,
            "expected": expected,
            "status": "open",
        })
        return badcase_id

    def recent(self, event_type: str = "query", limit: int = 50) -> List[Dict[str, Any]]:
        path = self.badcase_path if event_type == "badcase" else self.audit_path
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return list(reversed(records[-limit:]))

    @staticmethod
    def _append(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

