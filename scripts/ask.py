"""命令行体验确定性中文问数 MVP。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.nlq import NLQError, NaturalLanguageQueryEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="零售经营分析 Data Agent 问数 MVP")
    parser.add_argument("question", nargs="+", help="中文经营分析问题")
    args = parser.parse_args()
    question = " ".join(args.question)
    try:
        answer = NaturalLanguageQueryEngine(ROOT).answer(question)
    except NLQError as exc:
        print("无法回答：%s" % exc)
        raise SystemExit(2)
    print("问题：%s" % answer.question)
    print("解析：指标=%s，维度=%s，过滤=%s，时间=%s，对比=%s" % (
        answer.parsed.metric.display_name,
        answer.parsed.dimensions or "整体",
        dict(answer.parsed.filters) or "无",
        answer.parsed.date_range.label,
        answer.parsed.comparison or "无",
    ))
    print("说明：%s" % answer.explanation)
    print("SQL：\n%s" % answer.sql)
    if answer.comparison_sql:
        print("对比 SQL：\n%s" % answer.comparison_sql)
    print("结果：")
    print(json.dumps(answer.rows, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()

