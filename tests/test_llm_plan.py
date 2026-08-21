import unittest
from pathlib import Path

from app.agent.llm_nlq import DeepSeekNLQEngine, LLMPlanError


class LLMPlanValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 绕开 API 客户端，仅测试模型输出的计划校验。
        self.engine = object.__new__(DeepSeekNLQEngine)
        self.engine.root = Path(".")
        from app.agent.nlq import NaturalLanguageQueryEngine
        self.engine.deterministic = NaturalLanguageQueryEngine(Path("."))

    def test_accepts_valid_plan(self) -> None:
        parsed = self.engine._build_parsed_question("测试", {
            "metric": "sales_amount",
            "dimensions": ["region_name"],
            "filters": {"region_name": "华东"},
            "time_grain": "month",
            "start_date": "2025-11-01",
            "end_date": "2025-11-30",
            "comparison": "yoy",
            "clarification": None,
        })
        self.assertEqual(parsed.metric.name, "sales_amount")

    def test_rejects_unregistered_filter_value(self) -> None:
        with self.assertRaises(LLMPlanError):
            self.engine._build_parsed_question("测试", {
                "metric": "sales_amount",
                "dimensions": [],
                "filters": {"region_name": "不存在区域"},
                "time_grain": "month",
                "start_date": "2025-11-01",
                "end_date": "2025-11-30",
                "comparison": None,
                "clarification": None,
            })

    def test_relative_time_is_normalized_by_policy(self) -> None:
        parsed = self.engine._build_parsed_question("过去3个月各区域销售额趋势", {
            "metric": "sales_amount",
            "dimensions": ["region_name"],
            "filters": {},
            "time_grain": "month",
            # 模拟模型错误地多返回一个月；业务策略应覆盖模型日期。
            "start_date": "2025-09-01",
            "end_date": "2025-12-31",
            "comparison": None,
            "clarification": None,
        })
        self.assertEqual(parsed.date_range.start.isoformat(), "2025-10-01")
        self.assertEqual(parsed.date_range.end.isoformat(), "2025-12-31")


if __name__ == "__main__":
    unittest.main()
