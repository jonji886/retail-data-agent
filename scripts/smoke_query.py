"""验证语义层可以生成并执行一个聚合查询。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb

from app.semantic_layer.catalog import MetricCatalog


def main() -> None:
    db_path = ROOT / "data" / "retail.duckdb"
    catalog = MetricCatalog.from_file(ROOT / "configs" / "metrics" / "metrics.json")
    query = catalog.build_aggregate_query(
        "sales_amount",
        dimensions=["region_name"],
        time_grain="month",
        start_date="2025-10-01",
        end_date="2025-11-30",
    )
    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = connection.execute(query).fetchall()
    finally:
        connection.close()
    if not rows:
        raise SystemExit("烟囱查询没有返回结果")
    print("Smoke query passed")
    print(query)
    for row in rows:
        print("  ", row)


if __name__ == "__main__":
    main()
