"""推荐追问的结构化输出与会话上下文回归。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.agent.state import new_state
from app.agent.nodes.parse_request import _contextualize_follow_up
from app.agent.nlq import NaturalLanguageQueryEngine
from app.application import AgentApplicationService
from app.llm.openrouter_client import OpenRouterClient, OpenRouterConfig
from app.presentation.decision_support import build_recommended_questions


class FollowUpQuestionsTest(unittest.TestCase):
    def test_recommendations_are_non_empty_scoped_and_bounded(self) -> None:
        questions = build_recommended_questions(
            "attribution_analysis",
            {
                "scope": "华东",
                "dimension": "store_name",
                "current_period": "2025-11",
                "comparison_period": "2025-10",
                "current_total": 100,
                "comparison_total": 120,
                "total_delta": -20,
                "top_negative": [],
            },
        )
        self.assertTrue(questions)
        self.assertLessEqual(len(questions), 4)
        self.assertEqual(len(questions), len(set(questions)))
        self.assertTrue(all(isinstance(item, str) and item.strip() for item in questions))

    def test_service_preserves_scope_and_returns_session_context(self) -> None:
        service = AgentApplicationService(Path("."))
        fake = new_state("销售额", user_id="user_store_01", role="store_manager",
                          data_scope={"scope": "store", "store_name": "上海旗舰店1店"})
        fake["query_plan"] = {"metric": "sales_amount", "dimensions": [], "start_date": "2025-11-01", "end_date": "2025-11-30"}
        with patch("app.application.run_agent", return_value=fake) as run:
            result = service.query(
                "销售额", user_id="user_store_01", role="store_manager",
                data_scope={"scope": "store", "store_name": "上海旗舰店1店"},
                session_context={"last_question": "上一个问题"},
            )
        self.assertEqual(run.call_args.kwargs["session_context"]["last_question"], "上一个问题")
        self.assertEqual(result["session_context"]["data_scope"]["scope"], "store")
        self.assertEqual(result["session_context"]["last_metric"], "sales_amount")

    def test_short_follow_up_inherits_metric_and_time_range(self) -> None:
        engine = NaturalLanguageQueryEngine(Path("."))
        expanded = _contextualize_follow_up(
            "那华东呢",
            {"last_query_plan": {
                "metric": "sales_amount", "filters": {},
                "start_date": "2025-11-01", "end_date": "2025-11-30",
            }},
            engine,
        )
        self.assertIn("华东", expanded)
        self.assertIn("销售额", expanded)
        self.assertIn("2025年11月", expanded)


class DeepSeekPrimaryConfigTest(unittest.TestCase):
    def test_deepseek_is_default_primary_and_openrouter_is_optional_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "deepseek-test",
            "OPENROUTER_API_KEY": "openrouter-test",
        }, clear=True):
            config = OpenRouterConfig.from_env(Path(directory))
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.model, "deepseek-chat")
        self.assertEqual(config.fallback_provider, "openrouter")

    def test_deepseek_can_run_without_openrouter_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "deepseek-test",
        }, clear=True):
            config = OpenRouterConfig.from_env(Path(directory))
        self.assertEqual(config.provider, "deepseek")
        self.assertFalse(config.openrouter_api_key)

    def test_rate_limit_is_classified_before_openrouter_fallback(self) -> None:
        class FakeRateLimitError(Exception):
            status_code = 429

        config = OpenRouterConfig(
            api_key="deepseek-test", provider="deepseek", model="deepseek-chat",
            max_retries=0, openrouter_api_key="openrouter-test",
        )
        client = OpenRouterClient(config)
        response = Mock(choices=[Mock(message=Mock(content="ok"))], usage=None)
        with patch.object(client._client.chat.completions, "create", side_effect=FakeRateLimitError("429")):
            with patch.object(client._openrouter_client.chat.completions, "create", return_value=response):
                client.complete_text("system", "user")
        self.assertEqual(client.last_call_metadata["fallback_reason"], "rate_limit")
        self.assertEqual(client.last_call_metadata["fallback_from"], "deepseek")

    def test_missing_openrouter_fallback_returns_graceful_error_metadata(self) -> None:
        config = OpenRouterConfig(
            api_key="deepseek-test", provider="deepseek", model="deepseek-chat", max_retries=0,
        )
        client = OpenRouterClient(config)
        with patch.object(client._client.chat.completions, "create", side_effect=TimeoutError("timeout")):
            with self.assertRaisesRegex(RuntimeError, "未配置可选 fallback") as raised:
                client.complete_text("system", "user")
        self.assertEqual(raised.exception.llm_metadata["error_category"], "timeout")
        self.assertFalse(raised.exception.llm_metadata["fallback_available"])


if __name__ == "__main__":
    unittest.main()
