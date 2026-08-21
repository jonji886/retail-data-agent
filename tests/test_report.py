import unittest
from pathlib import Path

from app.reporting.weekly_report import RetailReportBuilder
from app.tools.sql_runner import ReadOnlySQLRunner


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

    def test_report_shares_the_readonly_duckdb_configuration(self) -> None:
        """报告路径与 Agent 查询路径可以在同一进程中交替访问数据库。"""
        runner = ReadOnlySQLRunner(Path("data/retail.duckdb"))
        self.assertEqual(runner.query("SELECT 1 AS value"), [{"value": 1}])
        context = RetailReportBuilder(Path(".")).build_context("2025-11", "华东", "store_name")
        self.assertEqual(context.period, "2025-11")


if __name__ == "__main__":
    unittest.main()
