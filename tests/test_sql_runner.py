import unittest
from pathlib import Path

from app.tools.sql_runner import ReadOnlySQLRunner, SQLSafetyError


class ReadOnlySQLRunnerTest(unittest.TestCase):
    def test_accepts_select(self) -> None:
        self.assertEqual(ReadOnlySQLRunner.validate("SELECT 1"), "SELECT 1")

    def test_rejects_write_operation(self) -> None:
        with self.assertRaises(SQLSafetyError):
            ReadOnlySQLRunner.validate("UPDATE dim_store SET store_name = 'x'")

    def test_rejects_multiple_statements(self) -> None:
        with self.assertRaises(SQLSafetyError):
            ReadOnlySQLRunner.validate("SELECT 1; SELECT 2")


if __name__ == "__main__":
    unittest.main()

