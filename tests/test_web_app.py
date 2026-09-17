"""Streamlit 交互回归：覆盖首屏点击、空输入和关闭模型后的分析。"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WebAppInteractionTest(unittest.TestCase):
    TEST_ENV = {
        "DATA_SOURCE": "duckdb",
        "LLM_PROVIDER": "deepseek",
        "DEEPSEEK_API_KEY": "",
        "QWEN_API_KEY": "",
        "SILICONFLOW_API_KEY": "",
    }

    def make_app(self) -> AppTest:
        app = AppTest.from_file(str(PROJECT_ROOT / "app" / "web_app.py"), default_timeout=45)
        app.run()
        return app

    @staticmethod
    def assert_no_exceptions(app: AppTest) -> None:
        assert not app.exception, [str(item.value) for item in app.exception]

    def test_default_question_is_real_value_and_click_runs(self) -> None:
        with patch.dict(os.environ, self.TEST_ENV):
            app = self.make_app()
            self.assertEqual(app.text_input[0].value, "为什么华东区域 11 月销售额下降了？")
            app.button[0].click()
            app.run()
            self.assert_no_exceptions(app)
            self.assertIn("分析完成", [item.value for item in app.success])

    def test_empty_question_shows_actionable_warning(self) -> None:
        with patch.dict(os.environ, self.TEST_ENV):
            app = self.make_app()
            app.text_input[0].set_value("")
            app.button[0].click()
            app.run()
            self.assert_no_exceptions(app)
            self.assertIn("请输入经营问题后再开始分析。", [item.value for item in app.warning])

    def test_disabled_model_click_uses_deterministic_path(self) -> None:
        with patch.dict(os.environ, self.TEST_ENV):
            app = self.make_app()
            # 未配置主模型时复选框禁用且默认关闭；新版 AppTest 禁止与 disabled 控件交互
            self.assertTrue(app.checkbox[0].disabled)
            self.assertFalse(app.checkbox[0].value)
            app.button[0].click()
            app.button[0].click()
            app.run()
            self.assert_no_exceptions(app)
            self.assertIn("分析完成", [item.value for item in app.success])


if __name__ == "__main__":
    unittest.main()
