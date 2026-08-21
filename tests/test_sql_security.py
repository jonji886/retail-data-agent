"""DuckDB capability lockdown 与 SQL 资源边界的对抗性测试。"""

import tempfile
import unittest
from pathlib import Path

from app.semantic_layer.catalog import MetricCatalog
from app.tools.sql_runner import (
    ReadOnlySQLRunner,
    SQLExecutionPolicy,
    SQLResourceLimitError,
    SQLSafetyError,
    open_readonly_connection,
)


ROOT = Path(".")
DB = ROOT / "data" / "retail.duckdb"


class DuckDBCapabilityLockdownTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = ReadOnlySQLRunner(DB)

    def test_normal_queries_still_succeed(self) -> None:
        self.assertEqual(self.runner.query("SELECT 1 AS value"), [{"value": 1}])
        query = MetricCatalog.from_file(ROOT / "configs/metrics/metrics.json").build_aggregate_query(
            "sales_amount",
            dimensions=["region_name"],
            time_grain="month",
            start_date="2025-11-01",
            end_date="2025-11-30",
        )
        self.assertEqual(len(self.runner.query(query)), 4)

    def test_external_file_table_functions_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "secret.csv"
            secret.write_text("secret\nnot-for-sql\n", encoding="utf-8")
            for sql in (
                "SELECT * FROM read_csv('%s')" % secret,
                "SELECT * FROM read_text('%s')" % secret,
                "SELECT * FROM read_parquet('%s')" % (Path(directory) / "secret.parquet"),
            ):
                with self.subTest(sql=sql):
                    with self.assertRaises(SQLSafetyError) as raised:
                        self.runner.query(sql)
                    self.assertEqual(raised.exception.reason_code, "external_access_blocked")
                    self.assertNotIn(str(secret), str(raised.exception))

    def test_http_external_access_is_blocked_without_network_dependency(self) -> None:
        with self.assertRaises(SQLSafetyError) as raised:
            self.runner.query("SELECT * FROM 'https://example.invalid/data.parquet'")
        self.assertEqual(raised.exception.reason_code, "external_access_blocked")

    def test_configuration_cannot_reopen_external_access(self) -> None:
        connection = open_readonly_connection(DB)
        try:
            with self.assertRaises(Exception):  # DuckDB exception type varies by release.
                connection.execute("SET enable_external_access = true")
        finally:
            connection.close()

    def test_result_limit_is_enforced(self) -> None:
        runner = ReadOnlySQLRunner(DB, SQLExecutionPolicy(max_result_rows=2))
        with self.assertRaises(SQLResourceLimitError) as raised:
            runner.query("SELECT * FROM range(3)")
        self.assertEqual(raised.exception.reason_code, "result_limit_exceeded")

    def test_extension_management_is_rejected_by_application_guard(self) -> None:
        for sql in ("INSTALL json", "LOAD json"):
            with self.subTest(sql=sql):
                with self.assertRaises(SQLSafetyError) as raised:
                    self.runner.query(sql)
                self.assertIn(
                    raised.exception.reason_code,
                    {"non_select_not_allowed", "mutation_not_allowed"},
                )

    def test_multiple_trailing_statements_are_rejected(self) -> None:
        with self.assertRaises(SQLSafetyError) as raised:
            self.runner.query("SELECT 1;;")
        self.assertEqual(raised.exception.reason_code, "multiple_statements_not_allowed")


if __name__ == "__main__":
    unittest.main()
