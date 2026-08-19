#!/usr/bin/env python3
"""项目一致性检查：README / 配置 / 报告 / Web Demo 之间的数字与状态漂移检测。

检查项：
1. Golden 用例数 == configs/evaluation/golden_questions.json 实际数量
2. reports/evaluation_report.json 的 total / passed / 指标分母一致性
3. README "Project Status" 块中的核心数字（单一事实来源）与真实值一致
4. Web Demo Tab 数量 == app/web_app.py 实际 Tab 数量
5. LLM 报告不得出现 "0 LLM calls + 100% pass" 的误导组合

用法:
    python3 scripts/verify_project_consistency.py

任何一项失败都以非 0 exit code 退出。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]

README_PATH = ROOT / "README.md"
GOLDEN_PATH = ROOT / "configs" / "evaluation" / "golden_questions.json"
EVAL_REPORT_PATH = ROOT / "reports" / "evaluation_report.json"
LLM_REPORT_PATH = ROOT / "reports" / "llm_evaluation_report.json"
WEB_APP_PATH = ROOT / "app" / "web_app.py"

# README Project Status 块中允许的键（单一事实来源）
STATUS_KEYS = ("Golden cases", "Evaluation cases", "Demo scenarios", "Web tabs")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def readme_text() -> str:
    return README_PATH.read_text(encoding="utf-8")


def readme_status_values() -> Dict[str, str]:
    """从 README Project Status 块提取核心数字。"""
    text = readme_text()
    values: Dict[str, str] = {}
    for key in STATUS_KEYS:
        m = re.search(r"^%s:\s*(\S+)\s*$" % re.escape(key), text, re.MULTILINE)
        values[key] = m.group(1) if m else ""
    return values


def golden_case_count() -> int:
    data = load_json(GOLDEN_PATH)
    cases = data.get("cases", data if isinstance(data, list) else [])
    return len(cases)


def web_tab_count() -> int:
    text = WEB_APP_PATH.read_text(encoding="utf-8")
    m = re.search(r"st\.tabs\(\s*\[([^\]]+)\]", text)
    if not m:
        return -1
    return len(re.findall(r"\"[^\"]+\"", m.group(1)))


def main() -> int:
    errors: List[str] = []
    print("== Project Consistency Check ==")

    # 1. Golden 数量
    golden_total = golden_case_count()
    print("1) Golden dataset cases: %d (config)" % golden_total)
    status = readme_status_values()
    if status.get("Golden cases") and status["Golden cases"] != str(golden_total):
        print("  [FAIL] README Golden cases=%s, 实际 config=%d"
              % (status["Golden cases"], golden_total))
        errors.append("README Golden cases 漂移")
    else:
        print("  OK: README Golden cases 与 config 一致")

    # 2. Evaluation Report
    print("2) Evaluation report:")
    if not EVAL_REPORT_PATH.exists():
        print("  [FAIL] 缺少 reports/evaluation_report.json，请先运行 scripts/run_evaluation.py")
        errors.append("缺少 evaluation_report.json")
    else:
        report = load_json(EVAL_REPORT_PATH)
        if report.get("total") != golden_total:
            print("  [FAIL] evaluation_report total=%s 与 golden 数量 %d 不一致"
                  % (report.get("total"), golden_total))
            errors.append("evaluation_report total 漂移")
        else:
            print("  OK: evaluation_report total=%s 与 golden 数量一致" % report.get("total"))
        results = report.get("results", [])
        if len(results) != report.get("total"):
            print("  [FAIL] evaluation_report results 数量 %d 与 total %s 不一致"
                  % (len(results), report.get("total")))
            errors.append("evaluation_report results 数量漂移")
        exec_cases = report.get("executable_cases")
        non_exec = report.get("non_executable_cases")
        if exec_cases is None or non_exec is None:
            print("  [FAIL] evaluation_report 缺少 executable_cases / non_executable_cases（旧版报告）")
            errors.append("evaluation_report 缺少新指标")
        elif exec_cases + non_exec != report.get("total"):
            print("  [FAIL] executable(%s)+non_executable(%s) != total(%s)"
                  % (exec_cases, non_exec, report.get("total")))
            errors.append("指标分母不一致")
        else:
            print("  OK: 指标分母一致 (executable=%s, non_executable=%s)" % (exec_cases, non_exec))
        # executable_success_rate 校验
        er = report.get("executable_success_rate")
        exec_ok = sum(1 for r in results if r.get("executable") and r.get("execution_success"))
        if exec_cases and er is not None:
            expected = exec_ok / exec_cases
            if abs(expected - er) > 1e-9:
                print("  [FAIL] executable_success_rate 与用例明细不一致: report=%.4f 实际=%.4f"
                      % (er, expected))
                errors.append("executable_success_rate 计算漂移")
            else:
                print("  OK: executable_success_rate 与用例明细一致")

    # 3. README Status 块
    print("3) README Project Status 块:")
    if not any(status.values()):
        print("  [FAIL] README 缺少 Project Status 块（Golden cases / Web tabs 等）")
        errors.append("README 缺少 Project Status 块")
    else:
        print("  OK: %s" % status)

    # 4. Web Tabs
    tabs = web_tab_count()
    print("4) Web Demo tabs: %d (web_app.py)" % tabs)
    if tabs < 0:
        print("  [FAIL] 无法从 web_app.py 解析 Tab 数量")
        errors.append("无法解析 Web Demo Tab 数量")
    elif status.get("Web tabs") and status["Web tabs"] != str(tabs):
        print("  [FAIL] README Web tabs=%s, 实际 web_app.py=%d" % (status["Web tabs"], tabs))
        errors.append("README Web tabs 漂移")
    else:
        print("  OK: README Web tabs 与 web_app.py 一致")

    # 5. LLM 报告可信度
    print("5) LLM evaluation report:")
    if not LLM_REPORT_PATH.exists():
        print("  OK: 不存在（未配置 API Key 时符合预期，不做检查）")
    else:
        report = load_json(LLM_REPORT_PATH)
        mode = report.get("mode")
        calls = report.get("total_llm_calls")
        rate = report.get("overall_pass_rate")
        if mode != "llm":
            print("  [FAIL] LLM 报告 mode=%s 应为 llm（旧版报告，请删除或重新生成）" % mode)
            errors.append("LLM 报告 mode 异常")
        elif calls == 0 and rate == 1.0:
            print("  [FAIL] LLM 报告 0 calls 但 100% pass，存在误导，请重新生成")
            errors.append("LLM 报告 0 calls / 100% pass 误导")
        else:
            print("  OK: mode=%s, total=%s, passed=%s, llm_calls=%s, fallback=%s"
                  % (mode, report.get("total"), report.get("passed"), calls,
                     report.get("fallback_count")))

    if errors:
        print("\nConsistency check FAILED (%d issue(s)):" % len(errors))
        for e in errors:
            print("  - %s" % e)
        return 1
    print("\nConsistency check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
