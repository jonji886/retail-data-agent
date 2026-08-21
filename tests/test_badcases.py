"""Badcase 生命周期测试：验证 发现 → 修复 → 回归 闭环。"""

import unittest
from pathlib import Path

from app.quality.badcases import (
    DEMO_BADCASE,
    REAL_LLM_BADCASE,
    BadcaseManager,
    seed_known_badcases,
)


ROOT = Path(".")


class BadcaseLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        self.manager = BadcaseManager(self.root)

    def test_create_badcase(self) -> None:
        bc_id = self.manager.create(
            event_id="evt_1", question="测试问题", category="expression",
            reason="识别失败", expected="应返回结果", actual="返回空",
        )
        records = self.manager.list_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["badcase_id"], bc_id)
        self.assertEqual(records[0]["status"], "open")

    def test_resolve_badcase(self) -> None:
        bc_id = self.manager.create(
            event_id="evt_2", question="测试问题2", category="permission",
            reason="越权未拦截", expected="deny", actual="allow",
        )
        ok = self.manager.resolve(bc_id, root_cause="权限检查遗漏", fix="增加 store scope 检查",
                                  regression_case_id="g030", fixed_version="v2.0")
        self.assertTrue(ok)
        resolved = self.manager.list_resolved()
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["root_cause"], "权限检查遗漏")
        self.assertEqual(resolved[0]["regression_case_id"], "g030")

    def test_demo_badcase_regression_passes(self) -> None:
        """验证 demo badcase 的回归用例 g009 现在能 PASS。"""
        # g009 = "各区域营业额" → 应识别为 sales_amount, dimension=region_name
        from app.quality.evaluation import run_golden
        results = run_golden(ROOT)
        g009 = next((r for r in results if r.case_id == "g009"), None)
        self.assertIsNotNone(g009, "g009 用例应存在")
        self.assertTrue(g009.passed, "g009 回归应 PASS（营业额同义词已修复）")

    def test_demo_badcase_has_complete_lifecycle(self) -> None:
        """验证 demo badcase 记录字段完整。"""
        bc = DEMO_BADCASE
        self.assertEqual(bc["status"], "resolved")
        self.assertTrue(bc["root_cause"])
        self.assertTrue(bc["fix"])
        self.assertTrue(bc["regression_case_id"])
        self.assertTrue(bc["resolved_at"])

    def test_real_llm_badcase_is_linked_to_golden_regression(self) -> None:
        self.assertEqual(REAL_LLM_BADCASE["status"], "resolved")
        self.assertEqual(REAL_LLM_BADCASE["regression_case_id"], "g016")
        self.assertTrue(REAL_LLM_BADCASE["root_cause"])
        self.assertTrue(REAL_LLM_BADCASE["fix"])

        self.assertEqual(seed_known_badcases(self.root), ["bc_demo_001", "bc_llm_001"])
        records = {record["badcase_id"]: record for record in self.manager.list_all()}
        self.assertEqual(records["bc_llm_001"]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
