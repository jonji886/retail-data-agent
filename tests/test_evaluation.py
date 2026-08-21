"""Evaluation 2.0 测试：验证 ground truth、result accuracy、permission、unsupported。"""

import unittest
from pathlib import Path

from app.quality.evaluation import run_golden, run_golden_v2


ROOT = Path(".")


class EvaluationTest(unittest.TestCase):
    def test_golden_v2_returns_metrics(self) -> None:
        report = run_golden_v2(ROOT)
        self.assertGreater(report["total"], 0)
        self.assertGreater(report["passed"], 0)
        self.assertIn("overall_pass_rate", report)
        self.assertIn("plan_accuracy", report)

    def test_golden_v2_results_are_serialized_mappings(self) -> None:
        """Web 展示层使用 run_golden_v2 的 JSON-compatible 结果。"""
        report = run_golden_v2(ROOT)
        self.assertTrue(report["results"])
        result = report["results"][0]
        self.assertIsInstance(result, dict)
        self.assertIn("case_id", result)
        self.assertIsInstance(result.get("errors"), list)
        self.assertIn("executable_success_rate", report)
        self.assertGreater(report["executable_cases"], 0)
        # 执行成功率分母 = executable 用例，而非全部用例
        self.assertEqual(
            report["executable_cases"],
            sum(1 for r in report["results"] if r["executable"]),
        )

    def test_ground_truth_result_accuracy(self) -> None:
        """g023 有 ground_truth value=1371235.35，必须 PASS。"""
        results = run_golden(ROOT)
        g023 = next(r for r in results if r.case_id == "g023")
        self.assertTrue(g023.passed, "g023 should pass: %s" % g023.errors)
        self.assertTrue(g023.result_accuracy)

    def test_wrong_result_must_fail(self) -> None:
        """如果 ground_truth 数值错误，评测必须 FAIL。"""
        import json
        path = ROOT / "configs" / "evaluation" / "golden_questions.json"
        original = path.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            for case in data["cases"]:
                if case["id"] == "g023":
                    case["ground_truth"]["value"] = 999999.99  # 错误值
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            results = run_golden(ROOT)
            g023 = next(r for r in results if r.case_id == "g023")
            self.assertFalse(g023.passed, "错误 ground truth 应 FAIL")
        finally:
            path.write_text(original, encoding="utf-8")

    def test_unsupported_must_reject(self) -> None:
        results = run_golden(ROOT)
        security_cases = [r for r in results if r.category == "security"]
        self.assertTrue(all(r.passed for r in security_cases))

    def test_permission_cases_pass(self) -> None:
        results = run_golden(ROOT)
        perm_cases = [r for r in results if r.category == "permission"]
        self.assertTrue(perm_cases)
        self.assertTrue(all(r.passed for r in perm_cases))


if __name__ == "__main__":
    unittest.main()
