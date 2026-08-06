import json
import tempfile
import unittest
from pathlib import Path

from app.semantic_layer.catalog import MetricCatalog, SemanticLayerError


class MetricCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = MetricCatalog.from_file(Path("configs/metrics/metrics.json"))

    def test_loads_expected_metrics(self) -> None:
        self.assertIn("sales_amount", self.catalog.names())
        self.assertIn("gross_margin_rate", self.catalog.names())

    def test_resolves_display_name_and_synonym(self) -> None:
        self.assertEqual(self.catalog.resolve("销售额").name, "sales_amount")
        self.assertEqual(self.catalog.resolve("GMV").name, "sales_amount")

    def test_builds_grouped_query(self) -> None:
        query = self.catalog.build_aggregate_query(
            "sales_amount",
            dimensions=["region_name"],
            time_grain="month",
            start_date="2025-01-01",
            end_date="2025-03-31",
        )
        self.assertIn("date_trunc('month', sale_date)", query)
        self.assertIn("GROUP BY date_trunc('month', sale_date), region_name", query)

    def test_rejects_unsupported_dimension(self) -> None:
        with self.assertRaises(SemanticLayerError):
            self.catalog.build_aggregate_query("traffic", dimensions=["category_name"])

    def test_rejects_invalid_date(self) -> None:
        with self.assertRaises(SemanticLayerError):
            self.catalog.build_aggregate_query("sales_amount", start_date="2025/01/01")


if __name__ == "__main__":
    unittest.main()

