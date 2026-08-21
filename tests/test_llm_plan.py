import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.agent.llm_nlq import LLMPlanError, OpenRouterNLQEngine
from app.llm.openrouter_client import OpenRouterConfig


class LLMPlanValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 绕开 API 客户端，仅测试模型输出的计划校验。
        self.engine = object.__new__(OpenRouterNLQEngine)
        self.engine.root = Path(".")
        from app.agent.nlq import NaturalLanguageQueryEngine
        self.engine.deterministic = NaturalLanguageQueryEngine(Path("."))

    def test_accepts_valid_plan(self) -> None:
        parsed = self.engine._build_parsed_question("测试", {
            "metric": "sales_amount",
            "dimensions": ["region_name"],
            "filters": {"region_name": "华东"},
            "time_grain": "month",
            "start_date": "2025-11-01",
            "end_date": "2025-11-30",
            "comparison": "yoy",
            "clarification": None,
        })
        self.assertEqual(parsed.metric.name, "sales_amount")

    def test_rejects_unregistered_filter_value(self) -> None:
        with self.assertRaises(LLMPlanError):
            self.engine._build_parsed_question("测试", {
                "metric": "sales_amount",
                "dimensions": [],
                "filters": {"region_name": "不存在区域"},
                "time_grain": "month",
                "start_date": "2025-11-01",
                "end_date": "2025-11-30",
                "comparison": None,
                "clarification": None,
            })

    def test_relative_time_is_normalized_by_policy(self) -> None:
        parsed = self.engine._build_parsed_question("过去3个月各区域销售额趋势", {
            "metric": "sales_amount",
            "dimensions": ["region_name"],
            "filters": {},
            "time_grain": "month",
            # 模拟模型错误地多返回一个月；业务策略应覆盖模型日期。
            "start_date": "2025-09-01",
            "end_date": "2025-12-31",
            "comparison": None,
            "clarification": None,
        })
        self.assertEqual(parsed.date_range.start.isoformat(), "2025-10-01")
        self.assertEqual(parsed.date_range.end.isoformat(), "2025-12-31")

    def test_parse_calls_client_once_and_validates_plan(self) -> None:
        self.engine.client = Mock()
        self.engine.client.complete_json.return_value = json.dumps({
            "metric": "sales_amount",
            "dimensions": ["region_name"],
            "filters": {"region_name": "华东"},
            "time_grain": "month",
            "start_date": "2025-11-01",
            "end_date": "2025-11-30",
            "comparison": "mom",
            "clarification": None,
        })
        parsed = self.engine.parse("2025年11月华东区域销售额环比")
        self.assertEqual(parsed.metric.name, "sales_amount")
        self.engine.client.complete_json.assert_called_once()


class OpenRouterConfigTest(unittest.TestCase):
    def test_is_configured_only_checks_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(OpenRouterConfig.is_configured(root))
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key",
            }, clear=True):
                self.assertTrue(OpenRouterConfig.is_configured(root))

    def test_invalid_numeric_config_is_reported_as_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key",
                "OPENROUTER_TIMEOUT_SECONDS": "invalid",
            }, clear=True):
                with self.assertRaisesRegex(RuntimeError, "TIMEOUT_SECONDS"):
                    OpenRouterConfig.from_env(root)


if __name__ == "__main__":
    unittest.main()
