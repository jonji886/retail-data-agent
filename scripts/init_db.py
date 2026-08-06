"""将生成的 CSV 加载为 DuckDB 表，并补充分析视图。"""

from __future__ import annotations

from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "generated"
DB_PATH = ROOT / "data" / "retail.duckdb"


TABLES = {
    "dim_date": "dim_date.csv",
    "dim_region": "dim_region.csv",
    "dim_store": "dim_store.csv",
    "dim_product": "dim_product.csv",
    "dim_channel": "dim_channel.csv",
    "fact_sales_daily": "fact_sales_daily.csv",
    "fact_inventory_daily": "fact_inventory_daily.csv",
    "fact_traffic_daily": "fact_traffic_daily.csv",
}


def csv_path(filename: str) -> str:
    return str((DATA_DIR / filename).resolve()).replace("'", "''")


def main() -> None:
    if not (DATA_DIR / "fact_sales_daily.csv").exists():
        raise SystemExit("找不到生成数据，请先运行: python3 scripts/generate_data.py")

    connection = duckdb.connect(str(DB_PATH))
    try:
        for table_name, filename in TABLES.items():
            connection.execute(
                "CREATE OR REPLACE TABLE %s AS SELECT * FROM read_csv_auto('%s', HEADER=TRUE)"
                % (table_name, csv_path(filename))
            )

        connection.execute(
            """
            CREATE OR REPLACE VIEW v_sales_enriched AS
            SELECT
                s.sale_date,
                s.store_id,
                st.store_name,
                st.region_id,
                st.region_name,
                st.city_name,
                s.product_id,
                p.product_name,
                p.category_name,
                p.subcategory_name,
                p.brand_name,
                s.channel_id,
                c.channel_name,
                s.order_count,
                s.units_sold,
                s.sales_amount,
                s.cost_amount,
                s.gross_profit
            FROM fact_sales_daily s
            JOIN dim_store st USING (store_id)
            JOIN dim_product p USING (product_id)
            JOIN dim_channel c USING (channel_id)
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW v_inventory_enriched AS
            SELECT i.*, st.store_name, st.region_id, st.region_name, st.city_name,
                   p.product_name, p.category_name, p.subcategory_name, p.brand_name
            FROM fact_inventory_daily i
            JOIN dim_store st USING (store_id)
            JOIN dim_product p USING (product_id)
            """
        )
        connection.execute(
            """
            CREATE OR REPLACE VIEW v_traffic_enriched AS
            SELECT t.*, st.store_name, st.region_id, st.region_name, st.city_name,
                   c.channel_name
            FROM fact_traffic_daily t
            JOIN dim_store st USING (store_id)
            JOIN dim_channel c USING (channel_id)
            """
        )

        print("DuckDB initialized: %s" % DB_PATH)
        for table_name in TABLES:
            count = connection.execute("SELECT COUNT(*) FROM %s" % table_name).fetchone()[0]
            print("  %-24s %8d rows" % (table_name, count))
        print("  %-24s %8d rows" % ("v_sales_enriched", connection.execute("SELECT COUNT(*) FROM v_sales_enriched").fetchone()[0]))
    finally:
        connection.close()


if __name__ == "__main__":
    main()

