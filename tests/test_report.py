import unittest
from pathlib import Path

from app.reporting.weekly_report import RetailReportBuilder


class ReportTest(unittest.TestCase):
    def test_builds_context_and_markdown(self) -> None:
        builder = RetailReportBuilder(Path("."))
        context = builder.build_context("2025-11", "华东", "store_name")
        report = builder.to_markdown(context)
        self.assertEqual(context.period, "2025-11")
        self.assertTrue(context.kpis)
        self.assertTrue(context.anomalies)
        self.assertIn("## 四、异常预警", report)
        self.assertIn("华东", report)


if __name__ == "__main__":
    unittest.main()

