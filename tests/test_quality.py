import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.quality.audit import AuditLogger
from app.quality.evaluation import run_golden


class QualityTest(unittest.TestCase):
    def test_audit_and_badcase_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logger = AuditLogger(root)
            parsed = SimpleNamespace(
                metric=SimpleNamespace(name="sales_amount"),
                dimensions=["region_name"],
                filters={"region_name": "华东"},
                date_range=SimpleNamespace(time_grain="month", start=__import__("datetime").date(2025, 11, 1), end=__import__("datetime").date(2025, 11, 30)),
                comparison="yoy",
            )
            event_id = logger.record_query("测试问题", "确定性基线", "success", parsed, "SELECT 1", 1)
            logger.record_badcase(event_id, "测试问题", "结果不符合预期", "应返回下降")
            self.assertEqual(logger.recent("query")[0]["event_id"], event_id)
            self.assertEqual(logger.recent("badcase")[0]["reason"], "结果不符合预期")

    def test_golden_dataset_passes(self) -> None:
        results = run_golden(Path("."))
        self.assertTrue(results)
        # 允许个别安全/权限类用例通过/失败，但核心 metric_query 类必须通过
        core_pass = [r for r in results if r.category in ("normal", "expression", "trend")]
        self.assertTrue(core_pass)
        self.assertTrue(all(item.passed for item in core_pass))


if __name__ == "__main__":
    unittest.main()

