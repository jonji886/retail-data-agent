"""v1.0 生产化边界：配置、配额、重试和 API。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.agent.state import new_state
from app.application import AgentApplicationService
from app.config import DataSourceConfig
from app.data_sources.postgresql import PostgreSQLDataSource
from app.llm.openrouter_client import OpenRouterConfig, OpenRouterClient
from app.observability.quota import DemoQuota, QuotaConfig


ROOT = Path(".")


class DataSourceConfigTest(unittest.TestCase):
    def test_postgresql_config_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "DATA_SOURCE": "postgresql",
            "DATABASE_URL": "postgresql://example.invalid/db",
            "DB_POOL_SIZE": "3",
            "DB_CONNECT_TIMEOUT": "2",
            "DB_STATEMENT_TIMEOUT": "3000",
        }, clear=True):
            config = DataSourceConfig.from_env(Path(directory))
        self.assertEqual(config.kind, "postgresql")
        self.assertEqual(config.pool_size, 3)
        self.assertEqual(config.statement_timeout_ms, 3000)

    def test_postgresql_does_not_expose_database_url_in_adapter(self) -> None:
        source = PostgreSQLDataSource("postgresql://user:secret@example.invalid/db")
        self.assertEqual(source.dialect, "postgresql")
        self.assertEqual(source._driver_sql("SELECT * FROM t WHERE id = ?"), "SELECT * FROM t WHERE id = %s")


class QuotaTest(unittest.TestCase):
    def test_session_quota_blocks_before_next_call(self) -> None:
        quota = DemoQuota(QuotaConfig(enabled=True, session_limit=1, ip_daily_limit=10, global_daily_limit=10))
        self.assertEqual(quota.allow("session-1")[0], True)
        self.assertEqual(quota.allow("session-1")[0], False)

    def test_disabled_quota_allows_requests(self) -> None:
        quota = DemoQuota(QuotaConfig(enabled=False, session_limit=1, ip_daily_limit=1, global_daily_limit=1))
        for _ in range(3):
            self.assertTrue(quota.allow("session-1")[0])

    def test_service_does_not_call_agent_after_quota(self) -> None:
        quota = DemoQuota(QuotaConfig(enabled=True, session_limit=1, ip_daily_limit=10, global_daily_limit=10))
        service = AgentApplicationService(ROOT, quota=quota)
        fake_state = new_state("销售额")
        with patch("app.application.run_agent", return_value=fake_state) as run:
            service.query("销售额", use_llm=True, session_id="s1")
            blocked = service.query("销售额", use_llm=True, session_id="s1")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(blocked["error_type"], "QUOTA_EXCEEDED")


class LLMRetryTest(unittest.TestCase):
    def test_client_retries_once_and_records_retry_count(self) -> None:
        config = OpenRouterConfig(
            api_key="test", max_retries=1,
            fallback_models=("fallback/one", "fallback/two"),
        )
        client = OpenRouterClient(config)
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"ok": true}'))]
        response.usage = None
        with patch.object(client._client.chat.completions, "create", side_effect=[RuntimeError("timeout"), response]) as call:
            self.assertEqual(client.complete_json("system", "user"), '{"ok": true}')
        self.assertEqual(call.call_count, 2)
        self.assertEqual(client.last_call_metadata["retry_count"], 1)
        self.assertEqual(call.call_args.kwargs["extra_body"], {"models": ["fallback/one", "fallback/two"]})

    def test_openrouter_error_fails_over_to_deepseek(self) -> None:
        config = OpenRouterConfig(
            api_key="openrouter-test", max_retries=0,
            deepseek_api_key="deepseek-test", deepseek_model="deepseek-chat",
        )
        client = OpenRouterClient(config)
        response = Mock()
        response.choices = [Mock(message=Mock(content='{"ok": true}'))]
        response.usage = None
        with patch.object(client._client.chat.completions, "create", side_effect=RuntimeError("timeout")):
            with patch.object(client._deepseek_client.chat.completions, "create", return_value=response) as fallback_call:
                self.assertEqual(client.complete_json("system", "user"), '{"ok": true}')
        self.assertEqual(fallback_call.call_args.kwargs["model"], "deepseek-chat")
        self.assertEqual(client.last_call_metadata["provider"], "deepseek")
        self.assertTrue(client.last_call_metadata["fallback_used"])
        self.assertEqual(client.last_call_metadata["fallback_from"], "openrouter")

    def test_deepseek_configuration_is_loaded_without_exposing_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "openrouter-test",
            "DEEPSEEK_API_KEY": "deepseek-test",
            "DEEPSEEK_MODEL": "deepseek-chat",
        }, clear=True):
            config = OpenRouterConfig.from_env(Path(directory))
        self.assertEqual(config.deepseek_model, "deepseek-chat")
        self.assertEqual(config.deepseek_api_key, "deepseek-test")

    def test_parses_openrouter_fallback_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_MODEL": "provider/primary",
            "OPENROUTER_FALLBACK_MODELS": "provider/one, provider/two, provider/one",
        }, clear=True):
            config = OpenRouterConfig.from_env(Path(directory))
        self.assertEqual(config.model, "provider/primary")
        self.assertEqual(config.fallback_models, ("provider/one", "provider/two"))

    def test_evaluation_model_cannot_use_free_router(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "LLM_PROVIDER": "openrouter",
            "OPENROUTER_API_KEY": "test-key",
            "EVAL_LLM_MODEL": "openrouter/free",
        }, clear=True):
            self.assertFalse(OpenRouterConfig.is_configured(Path(directory), mode="evaluation"))
            with self.assertRaisesRegex(RuntimeError, "固定的具体模型"):
                OpenRouterConfig.from_env(Path(directory), mode="evaluation")


class APITest(unittest.TestCase):
    def test_health_and_query_boundary(self) -> None:
        from app.api import app
        client = TestClient(app)
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        self.assertEqual(client.get("/ready").json()["status"], "ready")
        response = client.post("/api/v1/query", json={
            "user_id": "user_hq", "question": "本月各区域销售额", "use_llm": False,
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["status"], {"success", "failed"})
        self.assertTrue(body["run_id"])


if __name__ == "__main__":
    unittest.main()
