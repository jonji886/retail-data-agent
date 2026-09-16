import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.agent.llm_nlq import LLMPlanError, SiliconFlowNLQEngine
from app.llm.siliconflow_client import SiliconFlowConfig


class LLMPlanValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        # 绕开 API 客户端，仅测试模型输出的计划校验。
        self.engine = object.__new__(SiliconFlowNLQEngine)
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

    def test_invalid_main_output_uses_reason_after_one_main_retry(self) -> None:
        valid = json.dumps({
            "metric": "sales_amount",
            "dimensions": [],
            "filters": {},
            "time_grain": "month",
            "start_date": "2025-11-01",
            "end_date": "2025-11-30",
            "comparison": None,
            "clarification": None,
        })
        self.engine.config = SiliconFlowConfig(
            api_key="test", model="main/model", reason_model="reason/model", max_retries=1,
        )
        self.engine.client = Mock()
        self.engine.client.complete_json.side_effect = ["not-json", "still-not-json", valid]
        parsed = self.engine.parse("2025年11月销售额")
        self.assertEqual(parsed.metric.name, "sales_amount")
        self.assertEqual(
            [call.kwargs["role"] for call in self.engine.client.complete_json.call_args_list],
            ["main", "main", "reason"],
        )


class SiliconFlowConfigTest(unittest.TestCase):
    def test_evaluation_engine_loads_pinned_evaluation_config(self) -> None:
        config = Mock()
        with patch("app.agent.llm_nlq.create_model_config", return_value=config) as load, \
             patch("app.agent.llm_nlq.create_model_client"):
            engine = SiliconFlowNLQEngine(Path("."), mode="evaluation")
        load.assert_called_once_with(Path("."), mode="evaluation")
        self.assertIs(engine.config, config)

    def test_is_configured_only_checks_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                self.assertFalse(SiliconFlowConfig.is_configured(root))
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "siliconflow",
                "SILICONFLOW_API_KEY": "test-key",
            }, clear=True):
                self.assertTrue(SiliconFlowConfig.is_configured(root))

    def test_invalid_numeric_config_is_reported_as_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {
                "LLM_PROVIDER": "siliconflow",
                "SILICONFLOW_API_KEY": "test-key",
                "LLM_TIMEOUT_SECONDS": "invalid",
            }, clear=True):
                with self.assertRaisesRegex(RuntimeError, "TIMEOUT_SECONDS"):
                    SiliconFlowConfig.from_env(root)


if __name__ == "__main__":
    unittest.main()
