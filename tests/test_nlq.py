import unittest
from pathlib import Path

from app.agent.nlq import NLQError, NaturalLanguageQueryEngine


class NaturalLanguageQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = NaturalLanguageQueryEngine(Path("."))

    def test_parses_metric_filter_and_month(self) -> None:
        parsed = self.engine.parse("2025年11月华东区域销售额")
        self.assertEqual(parsed.metric.name, "sales_amount")
        self.assertEqual(parsed.filters["region_name"], "华东")
        self.assertEqual(parsed.date_range.start.isoformat(), "2025-11-01")

    def test_parses_group_dimension_and_yoy(self) -> None:
        parsed = self.engine.parse("本月各区域销售额同比变化")
        self.assertEqual(parsed.dimensions, ["region_name"])
        self.assertEqual(parsed.comparison, "yoy")

    def test_parses_multi_month_range(self) -> None:
        parsed = self.engine.parse("过去6个月毛利率趋势")
        self.assertEqual(parsed.date_range.start.isoformat(), "2025-07-01")
        self.assertEqual(parsed.date_range.time_grain, "month")

    def test_rejects_unknown_metric(self) -> None:
        with self.assertRaises(NLQError):
            self.engine.parse("本月经营情况怎么样")


if __name__ == "__main__":
    unittest.main()

