"""DataSource Adapter 测试。"""

import unittest
from pathlib import Path

from app.data_sources.duckdb import DuckDBDataSource


DB = Path("data/retail.duckdb")


class DuckDBDataSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ds = DuckDBDataSource(DB)

    def test_execute_readonly(self) -> None:
        rows = self.ds.execute_readonly("SELECT 1 AS v")
        self.assertEqual(rows, [{"v": 1}])

    def test_get_metadata(self) -> None:
        meta = self.ds.get_metadata()
        self.assertIn("tables", meta)
        self.assertIn("fact_sales_daily", meta["tables"])
        self.assertGreater(meta["tables"]["fact_sales_daily"]["row_count"], 0)

    def test_get_date_range(self) -> None:
        min_date, max_date = self.ds.get_date_range()
        self.assertIsNotNone(min_date)
        self.assertIsNotNone(max_date)

    def test_health_check(self) -> None:
        self.assertTrue(self.ds.health_check())


if __name__ == "__main__":
    unittest.main()
