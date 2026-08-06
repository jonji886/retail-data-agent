"""展示销售预警和归因分析结果。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analytics.anomaly import SalesAnomalyDetector
from app.analytics.attribution import SalesAttributor


def main() -> None:
    parser = argparse.ArgumentParser(description="经营预警与归因分析")
    parser.add_argument("--month", default="2025-11", help="分析月份，格式 YYYY-MM")
    parser.add_argument("--region", default="华东", help="归因范围，可留空表示全部区域")
    parser.add_argument("--dimension", default="store_name", choices=["city_name", "store_name", "category_name", "brand_name", "channel_name"])
    args = parser.parse_args()

    detector = SalesAnomalyDetector(ROOT / "data" / "retail.duckdb")
    anomalies = detector.detect(args.month, entity_level="region")
    print("销售异常预警：")
    if not anomalies:
        print("  未发现超过阈值的区域异常")
    for item in anomalies:
        print("  [%s] %s：当前销售额 %.2f，基线 %.2f，变化率 %.2f%%；规则：%s" % (
            item.severity.upper(), item.entity_name, item.current_value, item.baseline_value, item.change_rate * 100, item.rule
        ))

    result = SalesAttributor(ROOT / "data" / "retail.duckdb").analyze(args.month, args.dimension, args.region or None)
    print("\n销售变化归因：")
    print("  范围：%s；当前 %s，对比 %s；变化额 %.2f" % (result.scope, result.current_period, result.comparison_period, result.total_delta))
    for item in result.top_negative:
        rate = "N/A" if item.contribution_rate is None else "%.2f%%" % (item.contribution_rate * 100)
        print("  - %s=%s：变化额 %.2f，贡献率 %s" % (item.dimension, item.member, item.delta, rate))


if __name__ == "__main__":
    main()

