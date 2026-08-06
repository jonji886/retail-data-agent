"""使用 DeepSeek-V4-Flash 进行中文问数。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.llm_nlq import DeepSeekNLQEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek 中文问数")
    parser.add_argument("question", nargs="+", help="中文经营分析问题")
    args = parser.parse_args()
    answer = DeepSeekNLQEngine(ROOT).answer(" ".join(args.question))
    print("模型：%s" % answer.parsed.metric.display_name)
    print("解析：维度=%s，过滤=%s，时间=%s，对比=%s" % (
        answer.parsed.dimensions or "整体",
        dict(answer.parsed.filters) or "无",
        answer.parsed.date_range.label,
        answer.parsed.comparison or "无",
    ))
    print("说明：%s" % answer.explanation)
    print("SQL：\n%s" % answer.sql)
    if answer.comparison_sql:
        print("对比 SQL：\n%s" % answer.comparison_sql)
    print("结果：\n%s" % json.dumps(answer.rows, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()

