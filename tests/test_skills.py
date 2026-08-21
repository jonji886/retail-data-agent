"""Skill 单元测试：验证各 Skill 的确定性业务逻辑。"""

import unittest
from datetime import date
from pathlib import Path

from app.agent.contracts import QueryPlan
from app.skills.anomaly_analysis import anomaly_analysis_skill
from app.skills.attribution_analysis import attribution_analysis_skill
from app.skills.metric_query import metric_query_skill
from app.skills.report_generation import report_generation_skill
from app.skills.trend_analysis import trend_analysis_skill


ROOT = Path(".")
CONTEXT = {"root": ROOT, "authorized_filters": {"region_name": "华东"},
           "user_id": "user_hq", "role": "hq_manager"}
STORE_CONTEXT = {"root": ROOT, "authorized_filters": {"store_id": "S001"},
                 "user_id": "user_store_01", "role": "store_manager"}


class MetricQuerySkillTest(unittest.TestCase):
    def test_returns_rows_and_sql(self) -> None:
        plan = QueryPlan(
            intent="metric_query", metric="sales_amount",
            dimensions=["region_name"], filters={"region_name": "华东"},
            time_grain="month", start_date=date(2025, 11, 1), end_date=date(2025, 11, 30),
            comparison="yoy",
        )
        result = metric_query_skill(plan, CONTEXT)
        self.assertTrue(result["success"])
        self.assertGreater(result["row_count"], 0)
        self.assertTrue(result["sql"])
        self.assertEqual(result["metric"], "sales_amount")


class TrendAnalysisSkillTest(unittest.TestCase):
    def test_returns_trend_points(self) -> None:
        plan = QueryPlan(
            intent="trend_analysis", metric="sales_amount",
            dimensions=["region_name"], filters={"region_name": "华东"},
            end_date=date(2025, 11, 30),
        )
        result = trend_analysis_skill(plan, CONTEXT)
        self.assertTrue(result["success"])
        self.assertGreater(result["trend_points"], 0)

    def test_respects_query_plan_time_range(self) -> None:
        """趋势 Skill 不得把“过去 3 个月”扩大为默认 6 个月。"""
        plan = QueryPlan(
            intent="trend_analysis", metric="sales_amount",
            dimensions=["region_name"], filters={},
            start_date=date(2025, 10, 1), end_date=date(2025, 12, 31),
        )
        result = trend_analysis_skill(plan, {"root": ROOT, "authorized_filters": {}})
        self.assertTrue(result["success"])
        self.assertEqual(result["trend_points"], 12)


class AnomalyAnalysisSkillTest(unittest.TestCase):
    def test_detects_east_anomaly(self) -> None:
        plan = QueryPlan(
            intent="anomaly_analysis", metric="sales_amount",
            filters={"region_name": "华东"}, report_month="2025-11",
            start_date=date(2025, 11, 1), end_date=date(2025, 11, 30),
        )
        result = anomaly_analysis_skill(plan, CONTEXT)
        self.assertTrue(result["success"])
        self.assertTrue(result["has_anomaly"])


class AttributionAnalysisSkillTest(unittest.TestCase):
    def test_returns_contributions(self) -> None:
        plan = QueryPlan(
            intent="attribution_analysis", metric="sales_amount",
            filters={"region_name": "华东"}, report_month="2025-11",
            attribution_dimension="store_name",
            start_date=date(2025, 11, 1), end_date=date(2025, 11, 30),
        )
        result = attribution_analysis_skill(plan, CONTEXT)
        self.assertTrue(result["success"])
        self.assertLess(result["total_delta"], 0)
        self.assertTrue(result["top_negative"])
        self.assertIn("贡献", result["limitations"])


class ReportGenerationSkillTest(unittest.TestCase):
    def test_generates_markdown(self) -> None:
        plan = QueryPlan(
            intent="report_generation", metric="sales_amount",
            filters={"region_name": "华东"}, report_month="2025-11",
            attribution_dimension="store_name",
        )
        result = report_generation_skill(plan, CONTEXT)
        self.assertTrue(result["success"])
        self.assertTrue(result["markdown"])
        self.assertIn("经营分析月报", result["markdown"])
        self.assertGreater(len(result["kpis"]), 0)


class StoreScopeTest(unittest.TestCase):
    """门店经理 Data Scope：anomaly/attribution/report 必须只看到本门店数据。"""

    def test_anomaly_scoped_to_own_store(self) -> None:
        plan = QueryPlan(
            intent="anomaly_analysis", metric="sales_amount",
            filters={}, report_month="2025-11",
            start_date=date(2025, 11, 1), end_date=date(2025, 11, 30),
        )
        result = anomaly_analysis_skill(plan, STORE_CONTEXT)
        self.assertTrue(result["success"])
        self.assertTrue(result["anomalies"])
        for item in result["anomalies"]:
            self.assertEqual(item["entity_level"], "store")
            self.assertEqual(item["entity_id"], "S001")

    def test_attribution_defaults_to_category_and_scoped(self) -> None:
        plan = QueryPlan(
            intent="attribution_analysis", metric="sales_amount",
            filters={}, report_month="2025-11",
            attribution_dimension=None,
            start_date=date(2025, 11, 1), end_date=date(2025, 11, 30),
        )
        result = attribution_analysis_skill(plan, STORE_CONTEXT)
        self.assertTrue(result["success"])
        self.assertEqual(result["scope"], "S001")
        self.assertEqual(result["dimension"], "category_name")

    def test_report_scoped_to_own_store(self) -> None:
        plan = QueryPlan(
            intent="report_generation", metric="sales_amount",
            filters={}, report_month="2025-11",
            attribution_dimension=None,
        )
        result = report_generation_skill(plan, STORE_CONTEXT)
        self.assertTrue(result["success"])
        self.assertEqual(result["scope"], "S001")
        self.assertEqual(result["attribution_dimension"], "category_name")


if __name__ == "__main__":
    unittest.main()
