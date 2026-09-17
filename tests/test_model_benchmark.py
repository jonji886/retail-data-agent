"""Provider-agnostic configuration, usage, and Benchmark unit tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.llm.pricing import estimate_cost, estimate_tokens
from app.llm.siliconflow_client import ModelConfig, OpenAICompatibleClient
from app.quality.model_benchmark import render_markdown, summarize_provider


class QwenProviderTest(unittest.TestCase):
    def test_qwen_configuration_uses_standard_provider_scoped_variables(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "qwen",
            "QWEN_API_KEY": "test-key",
            "QWEN_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "QWEN_MAIN_MODEL": "qwen3.8-flash",
            "EVAL_LLM_MODEL": "qwen3.8-flash",
        }, clear=True):
            config = ModelConfig.from_env(Path(directory), mode="evaluation")
        self.assertEqual(config.provider, "qwen")
        self.assertEqual(config.model, "qwen3.8-flash")
        self.assertEqual(config.base_url, "https://dashscope.aliyuncs.com/compatible-mode/v1")

    def test_deepseek_provider_is_a_valid_direct_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "test-key",
            "DEEPSEEK_MAIN_MODEL": "deepseek-flash",
        }, clear=True):
            config = ModelConfig.from_env(Path(directory), mode="evaluation")
        self.assertEqual(config.provider, "deepseek")
        self.assertEqual(config.model, "deepseek-flash")
        self.assertEqual(config.base_url, "https://api.deepseek.com")

    def test_missing_qwen_key_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "qwen",
        }, clear=True):
            with self.assertRaisesRegex(RuntimeError, "QWEN_API_KEY"):
                ModelConfig.from_env(Path(directory))

    def test_openai_compatible_response_has_normalized_usage_metadata(self) -> None:
        config = ModelConfig(
            api_key="test-key", provider="qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen3.8-flash", main_model="qwen3.8-flash", max_retries=0,
        )
        client = OpenAICompatibleClient(config)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=3, total_tokens=23),
        )
        with patch.object(client._client.chat.completions, "create", return_value=response):
            self.assertEqual(client.complete_text("system", "user"), "ok")
        metadata = client.last_call_metadata
        for key in (
            "provider", "model", "role", "request_id", "trace_id", "latency_ms",
            "input_tokens", "output_tokens", "total_tokens", "estimated_cost",
            "success", "fallback_used",
        ):
            self.assertIn(key, metadata)
        self.assertEqual(metadata["provider"], "qwen")
        self.assertEqual(metadata["usage_source"], "provider")
        self.assertEqual((metadata["input_tokens"], metadata["output_tokens"], metadata["total_tokens"]), (20, 3, 23))
        self.assertAlmostEqual(metadata["estimated_cost"], 0.0000241)
        self.assertEqual(len(client.call_history), 1)


class ModelMetricsTest(unittest.TestCase):
    def test_token_estimation_and_cost_pricing(self) -> None:
        self.assertEqual(estimate_tokens("中文test"), 3)
        self.assertAlmostEqual(estimate_cost("qwen", "qwen3.8-flash", 20, 3), 0.0000241)
        self.assertIsNone(estimate_cost("unknown", "unknown", 20, 3))

    def test_benchmark_aggregates_physical_calls_errors_fallbacks_and_cost(self) -> None:
        records = [
            {"is_model_call": True, "success": True, "status": "success", "latency_ms": 80,
             "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "usage_source": "provider",
             "estimated_cost": 0.0001, "cost_currency": "USD"},
            {"is_model_call": True, "success": False, "status": "error", "latency_ms": 20,
             "input_tokens": 10, "output_tokens": None, "total_tokens": None, "usage_source": "unavailable",
             "estimated_cost": None, "fallback_used": False},
            {"is_model_call": True, "success": True, "status": "success", "latency_ms": 40,
             "input_tokens": 8, "output_tokens": 4, "total_tokens": 12, "usage_source": "estimated",
             "estimated_cost": 0.0002, "cost_currency": "USD", "fallback_used": True},
            {"is_model_call": False, "status": "fallback", "fallback_used": True},
        ]
        summary = summarize_provider("deepseek", "DeepSeek API", "deepseek-flash", [
            {"case_id": "g1", "passed": True, "latency_ms": 100, "llm_calls": records[:2]},
            {"case_id": "g2", "passed": False, "latency_ms": 200, "llm_calls": records[2:]},
        ])
        self.assertEqual(summary["golden_cases"], 2)
        self.assertEqual(summary["failed_cases"], 1)
        self.assertEqual(summary["llm_calls"], 3)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["fallback_calls"], 2)
        self.assertEqual(summary["input_tokens"], 28)
        self.assertEqual(summary["output_tokens"], 9)
        self.assertEqual(summary["total_tokens"], 27)
        self.assertEqual(summary["average_latency_ms"], 150)
        self.assertEqual(summary["p95_latency_ms"], 200)
        self.assertFalse(summary["estimated_cost_complete"])
        self.assertAlmostEqual(summary["estimated_cost"], 0.0003)

    def test_markdown_report_marks_skips_and_does_not_leak_secrets(self) -> None:
        report = {
            "generated_at": "2026-09-16T00:00:00+00:00",
            "dataset": {"version": "2.0", "cases_per_run": 1},
            "runs": 1,
            "data_source": "postgresql",
            "latency_note": "case latency",
            "cost_note": "not an invoice",
            "models": [
                {"provider": "deepseek", "provider_display_name": "DeepSeek API", "model": "deepseek-flash",
                 "status": "completed", "golden_cases": 1, "passed": 0, "failed": 1,
                 "success_rate": 0, "average_latency_ms": 50, "p95_latency_ms": 50,
                 "input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                 "average_tokens_per_case": 2, "estimated_cost": None, "estimated_cost_currency": None,
                 "estimated_cost_complete": False, "llm_calls": 1, "errors": 1, "error_rate": 1,
                 "fallback_calls": 0, "failed_cases": 1, "unpriced_calls": 1, "usage_sources": {},
                 "results": [{"case_id": "g1", "passed": False, "failure_stage": "provider",
                              "expected": {}, "actual": {}, "errors": ["api_key=sk-1234567890"]}]},
                {"provider": "qwen", "provider_display_name": "Qwen", "model": "qwen3.8-flash",
                 "status": "skipped", "skip_reason": "missing QWEN_API_KEY"},
            ],
            "conclusion": "not comparable",
        }
        markdown = render_markdown(report)
        self.assertIn("Qwen", markdown)
        self.assertIn("skipped", markdown)
        self.assertIn("[REDACTED]", markdown)
        self.assertNotIn("sk-1234567890", markdown)
        self.assertIn("not an invoice", markdown)


class MockProviderBenchmarkTest(unittest.TestCase):
    def test_one_case_error_does_not_abort_mock_provider_run(self) -> None:
        from scripts import run_model_benchmark

        fake_config = SimpleNamespace(model="deepseek-flash")
        passing_state = {
            "intent": "metric_query",
            "query_plan": {"metric": "sales_amount", "dimensions": [], "filters": {}},
            "result": {"success": True},
            "llm_calls": [{"is_model_call": True, "success": True, "status": "success",
                           "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
                           "estimated_cost": 0.00001, "cost_currency": "USD", "usage_source": "provider"}],
        }
        cases = [
            {"id": "g1", "question": "one", "intent": "metric_query"},
            {"id": "g2", "question": "two", "intent": "metric_query"},
        ]
        with patch.dict(os.environ, {"LLM_PROVIDER": "deepseek", "DEEPSEEK_API_KEY": "test-key"}, clear=True), \
             patch.object(run_model_benchmark.ModelConfig, "from_env", return_value=fake_config), \
             patch.object(run_model_benchmark, "run_agent", side_effect=[RuntimeError("case failed"), passing_state]):
            summary = run_model_benchmark._run_provider("deepseek", "DeepSeek API", Path("."), cases, 1, object())
        self.assertEqual(summary["golden_cases"], 2)
        self.assertEqual(summary["failed_cases"], 1)
        self.assertEqual(summary["llm_calls"], 1)


if __name__ == "__main__":
    unittest.main()
