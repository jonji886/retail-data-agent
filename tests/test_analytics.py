import unittest
from pathlib import Path

from app.analytics.anomaly import SalesAnomalyDetector
from app.analytics.attribution import SalesAttributor


class AnalyticsTest(unittest.TestCase):
    DB = Path("data/retail.duckdb")

    def test_detects_injected_region_anomaly(self) -> None:
        anomalies = SalesAnomalyDetector(self.DB).detect("2025-11", entity_level="region")
        self.assertTrue(any(item.entity_name == "华东" for item in anomalies))
        east = next(item for item in anomalies if item.entity_name == "华东")
        self.assertLess(east.change_rate, -0.15)

    def test_attributes_region_sales_change_by_store(self) -> None:
        result = SalesAttributor(self.DB).analyze("2025-11", dimension="store_name", region_name="华东")
        self.assertLess(result.total_delta, 0)
        self.assertEqual(len(result.contributions), 4)
        self.assertTrue(result.top_negative)


if __name__ == "__main__":
    unittest.main()

