#!/usr/bin/env python3
"""生成 Web Demo 真实运行截图（docs/assets/），用于 README 作品集展示。

需要：
- playwright（pip install playwright && playwright install chromium）
- 项目依赖已安装

流程：
1. 启动 Streamlit（若未运行）
2. 打开 Agent Tab，运行归因问题，截取回答主界面
3. 展开执行链路 / Trace，截取链路明细
4. 打开质量评测 Tab，截取指标面板

用法:
    python3 scripts/capture_demo_shots.py

输出:
    docs/assets/agent-demo.png
    docs/assets/agent-trace.png
    docs/assets/evaluation.png
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
STREAMLIT_URL = "http://localhost:8501"
QUESTION = "为什么华东区域 11 月销售额下降了？"


def ensure_streamlit() -> None:
    try:
        import urllib.request

        urllib.request.urlopen(STREAMLIT_URL, timeout=2)
        return
    except Exception:
        pass
    print("Starting streamlit...")
    subprocess.Popen(
        [str(ROOT / ".venv/bin/streamlit"), "run", "app/web_app.py",
         "--server.headless", "true", "--server.port", "8501"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        time.sleep(1)
        try:
            import urllib.request

            urllib.request.urlopen(STREAMLIT_URL, timeout=2)
            return
        except Exception:
            continue
    sys.exit("streamlit did not start within 30s")


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("缺少 playwright：pip install playwright && playwright install chromium")

    ensure_streamlit()
    ASSETS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(STREAMLIT_URL, wait_until="networkidle")
        time.sleep(4)

        # Tab 1: Agent 归因场景
        page.get_by_text("Agent", exact=True).first.click()
        time.sleep(2)
        # Streamlit st.text_input 渲染为 <input> role=textbox
        input_el = page.get_by_role("textbox").first
        input_el.fill(QUESTION)
        page.get_by_role("button", name="执行 Agent", exact=True).first.click()
        time.sleep(8)
        page.screenshot(path=str(ASSETS / "agent-demo.png"), full_page=False)
        print("saved docs/assets/agent-demo.png")

        # 展开执行链路 / Trace
        try:
            page.get_by_text("查看 SQL、指标口径与 Trace", exact=False).first.click()
            time.sleep(2)
        except Exception:
            pass
        page.screenshot(path=str(ASSETS / "agent-trace.png"), full_page=False)
        print("saved docs/assets/agent-trace.png")

        # Tab 2: 质量评测
        page.get_by_text("质量评测", exact=True).first.click()
        time.sleep(6)
        page.screenshot(path=str(ASSETS / "evaluation.png"), full_page=False)
        print("saved docs/assets/evaluation.png")

        browser.close()
    print("done: docs/assets/")


if __name__ == "__main__":
    main()
