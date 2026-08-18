"""权限测试：RBAC + Data Scope 覆盖 HQ / Region / Store / Cross。"""

import unittest
from pathlib import Path

from app.tools.permission import PermissionChecker


ROOT = Path(".")


class PermissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = PermissionChecker(ROOT)

    def test_hq_can_query_all(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_hq", {})
        self.assertTrue(allow)
        self.assertEqual(filters, {})

    def test_hq_can_query_specific_region(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_hq", {"region_name": "华南"})
        self.assertTrue(allow)

    def test_region_manager_can_query_own_region(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_east", {"region_name": "华东"})
        self.assertTrue(allow)

    def test_region_manager_denied_cross_region(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_east", {"region_name": "华南"})
        self.assertFalse(allow)
        self.assertIn("华南", reason)

    def test_region_manager_auto_injected_region(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_east", {})
        self.assertTrue(allow)
        self.assertEqual(filters["region_name"], "华东")

    def test_store_manager_can_query_own_store(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize(
            "user_store_01", {"store_id": "STORE_001"})
        self.assertTrue(allow)

    def test_store_manager_denied_cross_store(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize(
            "user_store_01", {"store_id": "STORE_002"})
        self.assertFalse(allow)

    def test_store_manager_auto_injected_store(self) -> None:
        allow, filters, reason = self.checker.check_and_authorize("user_store_01", {})
        self.assertTrue(allow)
        self.assertEqual(filters["store_id"], "STORE_001")

    def test_store_manager_denied_cross_region_even_without_store(self) -> None:
        # 门店经理查询其它区域应被拒绝
        allow, filters, reason = self.checker.check_and_authorize(
            "user_store_01", {"region_name": "华南"})
        self.assertFalse(allow)

    def test_unknown_user_denied(self) -> None:
        from app.tools.permission import PermissionError
        with self.assertRaises(PermissionError):
            self.checker.check_and_authorize("unknown_user", {})


if __name__ == "__main__":
    unittest.main()
