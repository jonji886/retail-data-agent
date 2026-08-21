#!/usr/bin/env python3
"""项目一致性检查：README / 配置 / 报告 / Web Demo 之间的数字与状态漂移检测。

检查项：
1. Golden 用例数 == configs/evaluation/golden_questions.json 实际数量
2. reports/evaluation_report.json 的 total / passed / 指标分母一致性
3. README "Project Status" 块中的核心数字（单一事实来源）与真实值一致
4. Web Demo Tab 数量 == app/web_app.py 实际 Tab 数量
5. LLM 报告不得出现 "0 LLM calls + 100% pass" 的误导组合
6. README Evaluation 数字必须与 deterministic / LLM 报告一致
7. README / SPEC version、verification date、测试文件数和测试用例数一致

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
SPEC_PATH = ROOT / "SPEC.md"
TESTS_DIR = ROOT / "tests"

# README Project Status 块中允许的键（单一事实来源）
STATUS_KEYS = (
    "Version", "Last verified", "Primary LLM Provider", "Golden cases", "Evaluation cases", "Demo scenarios",
    "Web tabs", "Unit test files", "Unit tests",
)


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


def test_file_count() -> int:
    return len(list(TESTS_DIR.glob("test_*.py")))


def test_case_count() -> int:
    return sum(
        len(re.findall(r"^\s+def test_", path.read_text(encoding="utf-8"), re.MULTILINE))
        for path in TESTS_DIR.glob("test_*.py")
    )


def spec_metadata() -> Dict[str, str]:
    text = SPEC_PATH.read_text(encoding="utf-8")
    return {
        "Version": (re.search(r"^Version:\s*(\S+)", text, re.MULTILINE) or ["", ""])[1],
        "Last verified": (re.search(r"^Last verified:\s*(\S+)", text, re.MULTILINE) or ["", ""])[1],
    }


def web_tab_count() -> int:
    text = WEB_APP_PATH.read_text(encoding="utf-8")
    m = re.search(r"st\.tabs\(\s*\[([^\]]+)\]", text)
    if not m:
        return -1
    return len(re.findall(r"\"[^\"]+\"", m.group(1)))


def _readme_section(title: str, next_title: str) -> str:
    text = readme_text()
    start = text.find(title)
    if start < 0:
        return ""
    end = text.find(next_title, start + len(title))
    return text[start:] if end < 0 else text[start:end]


def _readme_table_value(section: str, label: str) -> str:
    match = re.search(
        r"^\|\s*%s\s*\|\s*(.*?)\s*\|\s*$" % re.escape(label),
        section,
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def _percentage_matches(value: str, expected_rate: Any) -> bool:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)%", value)
    return bool(match) and abs(float(match.group(1)) - float(expected_rate) * 100) < 0.05


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

    # 1b. README / SPEC 元信息与测试规模
    spec = spec_metadata()
    print("1b) Project metadata and tests:")
    if status.get("Version") != spec.get("Version"):
        print("  [FAIL] README Version=%s, SPEC Version=%s" % (status.get("Version"), spec.get("Version")))
        errors.append("README/SPEC version 漂移")
    if status.get("Last verified") != spec.get("Last verified"):
        print("  [FAIL] README Last verified=%s, SPEC Last verified=%s" % (status.get("Last verified"), spec.get("Last verified")))
        errors.append("README/SPEC verification date 漂移")
    actual_test_files = test_file_count()
    actual_tests = test_case_count()
    if status.get("Unit test files") != str(actual_test_files):
        print("  [FAIL] README Unit test files=%s, 实际=%s" % (status.get("Unit test files"), actual_test_files))
        errors.append("README 测试文件数漂移")
    if status.get("Unit tests") != str(actual_tests):
        print("  [FAIL] README Unit tests=%s, 实际=%s" % (status.get("Unit tests"), actual_tests))
        errors.append("README 测试用例数漂移")
    if (
        status.get("Version") == spec.get("Version")
        and status.get("Last verified") == spec.get("Last verified")
        and status.get("Unit test files") == str(actual_test_files)
        and status.get("Unit tests") == str(actual_tests)
    ):
        print("  OK: version/date/test counts consistent")

    # 2. Evaluation Report
    print("2) Evaluation report:")
    if not EVAL_REPORT_PATH.exists():
        print("  [FAIL] 缺少 reports/evaluation_report.json，请先运行 scripts/run_evaluation.py")
        errors.append("缺少 evaluation_report.json")
    else:
        report = load_json(EVAL_REPORT_PATH)
        if report.get("mode") not in (None, "deterministic"):
            print("  [FAIL] deterministic report mode=%s 异常" % report.get("mode"))
            errors.append("deterministic report mode 异常")
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

    # 4b. Provider 默认值：配置、README 与主客户端必须一致。
    print("4b) Primary LLM Provider:")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    provider_match = re.search(r"^LLM_PROVIDER=(\S+)", env_example, re.MULTILINE)
    default_provider = provider_match.group(1).lower() if provider_match else ""
    if default_provider != "deepseek" or status.get("Primary LLM Provider") != "DeepSeek":
        print("  [FAIL] 默认 Provider 应为 DeepSeek（env=%s, README=%s）" % (
            default_provider, status.get("Primary LLM Provider")))
        errors.append("Primary LLM Provider 漂移")
    else:
        print("  OK: DeepSeek 为默认主 Provider，OpenRouter 仅作可选 fallback")

    # 5. LLM 报告可信度
    print("5) LLM evaluation report:")
    if not LLM_REPORT_PATH.exists():
        llm_section = _readme_section(
            "### 真实 LLM 端到端评测", "### 已知 / 已修复的失败案例"
        )
        if "未生成" not in llm_section:
            print("  [FAIL] LLM 报告不存在，但 README 未明确标记当前没有真实报告")
            errors.append("README LLM 无报告说明缺失")
        else:
            print("  OK: 当前没有真实 LLM 报告，README 已明确说明")
    else:
        report = load_json(LLM_REPORT_PATH)
        mode = report.get("mode")
        calls = report.get("total_llm_calls")
        rate = report.get("overall_pass_rate")
        if mode != "llm":
            print("  [FAIL] LLM 报告 mode=%s 应为 llm（旧版报告，请删除或重新生成）" % mode)
            errors.append("LLM 报告 mode 异常")
        elif report.get("total") != golden_total:
            print("  [FAIL] LLM 报告 total=%s 与 golden 数量 %s 不一致" % (report.get("total"), golden_total))
            errors.append("LLM 报告 total 漂移")
        elif len(report.get("results", [])) != report.get("total"):
            print("  [FAIL] LLM 报告 results 数量与 total 不一致")
            errors.append("LLM 报告 results 数量漂移")
        elif calls == 0 and rate == 1.0:
            print("  [FAIL] LLM 报告 0 calls 但 100% pass，存在误导，请重新生成")
            errors.append("LLM 报告 0 calls / 100% pass 误导")
        else:
            print("  OK: mode=%s, total=%s, passed=%s, llm_calls=%s, fallback=%s"
                  % (mode, report.get("total"), report.get("passed"), calls,
                     report.get("fallback_count")))

    # 6) README Evaluation 证据必须来自报告，而不是独立维护的数字。
    print("6) README Evaluation evidence:")
    deterministic_section = _readme_section(
        "### 确定性回归", "### 真实 LLM 端到端评测"
    )
    if EVAL_REPORT_PATH.exists():
        deterministic = load_json(EVAL_REPORT_PATH)
        overall_value = _readme_table_value(deterministic_section, "总体通过率")
        executable_value = _readme_table_value(deterministic_section, "可执行用例成功率")
        expected_overall_ratio = "%d/%d" % (
            deterministic.get("passed", 0), deterministic.get("total", 0)
        )
        expected_executable_ratio = "%d/%d" % (
            sum(
                1
                for item in deterministic.get("results", [])
                if item.get("executable") and item.get("execution_success")
            ),
            deterministic.get("executable_cases", 0),
        )
        if (
            expected_overall_ratio not in overall_value
            or not _percentage_matches(overall_value, deterministic.get("overall_pass_rate", 0))
        ):
            print("  [FAIL] README deterministic Overall Pass Rate 与报告不一致")
            errors.append("README deterministic Overall Pass Rate 漂移")
        elif (
            expected_executable_ratio not in executable_value
            or not _percentage_matches(
                executable_value, deterministic.get("executable_success_rate", 0)
            )
        ):
            print("  [FAIL] README deterministic Executable Success Rate 与报告不一致")
            errors.append("README deterministic Executable Success Rate 漂移")
        else:
            print("  OK: README deterministic 指标与报告一致")

    if LLM_REPORT_PATH.exists():
        llm = load_json(LLM_REPORT_PATH)
        llm_section = _readme_section(
            "### 真实 LLM 端到端评测", "### 已知 / 已修复的失败案例"
        )
        expected_llm = "%d/%d" % (llm.get("passed", 0), llm.get("total", 0))
        expected_calls = str(llm.get("total_llm_calls"))
        if (
            expected_llm not in llm_section
            or expected_calls not in _readme_table_value(llm_section, "LLM 调用")
        ):
            print("  [FAIL] README LLM 指标与真实报告不一致")
            errors.append("README LLM 指标漂移")
        else:
            print("  OK: README LLM 指标与真实报告一致")

    if errors:
        print("\nConsistency check FAILED (%d issue(s)):" % len(errors))
        for e in errors:
            print("  - %s" % e)
        return 1
    print("\nConsistency check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
