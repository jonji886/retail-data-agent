"""相对时间策略回归测试：固定 reference_date，避免测试随系统日期漂移。"""

import unittest
from datetime import date
from pathlib import Path

from app.agent.nlq import NaturalLanguageQueryEngine
from app.domain.time_range import resolve_relative_time


class RelativeTimePolicyTest(unittest.TestCase):
    REFERENCE_DATE = date(2026, 8, 20)

    def assert_range(self, question: str, start: str, end: str, grain: str) -> None:
        result = resolve_relative_time(question, self.REFERENCE_DATE)
        self.assertIsNotNone(result, question)
        assert result is not None
        self.assertEqual(result.start_date.isoformat(), start, question)
        self.assertEqual(result.end_date.isoformat(), end, question)
        self.assertEqual(result.grain, grain, question)

    def test_month_phrases_share_one_policy(self) -> None:
        for phrase in ("过去3个月", "最近3个月", "近3个月", "近三个月"):
            self.assert_range(phrase, "2026-06-01", "2026-08-20", "month")

    def test_current_previous_year_and_month(self) -> None:
        self.assert_range("本月", "2026-08-01", "2026-08-20", "month")
        self.assert_range("上个月", "2026-07-01", "2026-07-31", "month")
        self.assert_range("今年", "2026-01-01", "2026-08-20", "month")
        self.assert_range("去年", "2025-01-01", "2025-12-31", "month")

    def test_day_phrases_are_inclusive_rolling_windows(self) -> None:
        self.assert_range("过去30天", "2026-07-22", "2026-08-20", "day")
        self.assert_range("最近90天", "2026-05-23", "2026-08-20", "day")

    def test_engine_uses_the_same_month_policy(self) -> None:
        engine = NaturalLanguageQueryEngine(Path("."))
        parsed = engine.parse("最近3个月各区域销售额趋势")
        self.assertEqual(parsed.date_range.start, date(2025, 10, 1))
        self.assertEqual(parsed.date_range.end, date(2025, 12, 31))
        self.assertEqual(parsed.date_range.time_grain, "month")


if __name__ == "__main__":
    unittest.main()
