"""生成确定性或 OpenRouter 润色后的经营分析月报。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.llm.openrouter_client import OpenRouterClient, OpenRouterConfig
from app.reporting.weekly_report import RetailReportBuilder


def main() -> None:
    parser = argparse.ArgumentParser(description="生成零售经营分析月报")
    parser.add_argument("--month", default="2025-11", help="报告月份 YYYY-MM")
    parser.add_argument("--region", default="华东", help="报告范围；不传则覆盖全部区域")
    parser.add_argument("--dimension", default="store_name", choices=["city_name", "store_name", "category_name", "brand_name", "channel_name"])
    parser.add_argument("--llm", action="store_true", help="使用 OpenRouter 组织报告文字")
    parser.add_argument("--output", type=Path, help="可选：保存 Markdown 文件")
    args = parser.parse_args()

    context = RetailReportBuilder(ROOT).build_context(args.month, args.region or None, args.dimension)
    if args.llm:
        client = OpenRouterClient(OpenRouterConfig.from_env(ROOT))
        report = RetailReportBuilder.to_openrouter_markdown(context, client)
    else:
        report = RetailReportBuilder.to_markdown(context)
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report + "\n", encoding="utf-8")
        print("报告已写入：%s" % output)
    else:
        print(report)


if __name__ == "__main__":
    main()
