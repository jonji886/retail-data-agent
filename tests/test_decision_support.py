"""老板视角展示模型测试。"""

import unittest

from app.presentation.decision_support import (
    build_attribution_summary,
    build_attribution_table,
    build_follow_up_questions,
    dimension_label,
)


class DecisionSupportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.result = {
            "scope": "华东",
            "current_period": "2025-11",
            "comparison_period": "2025-10",
            "current_total": 1371235.35,
            "comparison_total": 1846695.27,
            "total_delta": -475459.92,
            "dimension": "store_name",
            "top_negative": [
                {
                    "member": "上海旗舰店1店",
                    "dimension": "store_name",
                    "current_value": 300000,
                    "comparison_value": 430919.51,
                    "delta": -130919.51,
                    "contribution_rate": 0.2754,
                },
                {
                    "member": "上海标准店2店",
                    "dimension": "store_name",
                    "current_value": 250000,
                    "comparison_value": 370485.31,
                    "delta": -120485.31,
                    "contribution_rate": 0.2534,
                },
            ],
        }

    def test_summary_calculates_change_rate_and_business_labels(self) -> None:
        summary = build_attribution_summary(self.result)
        self.assertEqual(summary["direction"], "下降")
        self.assertAlmostEqual(summary["change_rate"], -0.2575, places=3)
        self.assertEqual(summary["dimension_label"], "门店")
        self.assertAlmostEqual(summary["top_two_contribution"], 0.5288, places=4)

    def test_table_uses_business_columns_and_positive_decline_amount(self) -> None:
        table = build_attribution_table(build_attribution_summary(self.result))
        self.assertEqual(table[0]["维度"], "门店")
        self.assertEqual(table[0]["成员"], "上海旗舰店1店")
        self.assertEqual(table[0]["下降金额"], 130919.51)
        self.assertEqual(table[0]["变化额"], -130919.51)

    def test_follow_up_questions_are_scoped_to_result(self) -> None:
        questions = build_follow_up_questions(build_attribution_summary(self.result))
        self.assertEqual(len(questions), 3)
        self.assertTrue(all("华东" in question for question in questions))
        self.assertIn("门店", questions[0])

    def test_unknown_dimension_has_safe_display_label(self) -> None:
        self.assertEqual(dimension_label("unknown_dimension"), "unknown_dimension")


if __name__ == "__main__":
    unittest.main()
