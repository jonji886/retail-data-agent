"""PostgreSQL/Supabase Demo Schema 与种子数据导入共用逻辑。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


TABLE_DEFINITIONS: Dict[str, str] = {
    "dim_date": """
        date_key DATE PRIMARY KEY, year INTEGER, quarter TEXT, month INTEGER,
        month_name TEXT, week_of_year INTEGER, day_of_week INTEGER,
        is_weekend BOOLEAN, is_holiday BOOLEAN
    """,
    "dim_region": """
        region_id TEXT PRIMARY KEY, region_name TEXT NOT NULL, region_manager TEXT
    """,
    "dim_store": """
        store_id TEXT PRIMARY KEY, store_name TEXT NOT NULL, region_id TEXT,
        region_name TEXT, city_name TEXT, store_type TEXT, opening_date DATE
    """,
    "dim_product": """
        product_id TEXT PRIMARY KEY, product_name TEXT NOT NULL, category_id TEXT,
        category_name TEXT, subcategory_name TEXT, brand_name TEXT,
        unit_cost DOUBLE PRECISION, unit_price DOUBLE PRECISION
    """,
    "dim_channel": """
        channel_id TEXT PRIMARY KEY, channel_name TEXT NOT NULL, channel_type TEXT
    """,
    "fact_sales_daily": """
        sale_date DATE NOT NULL, store_id TEXT, product_id TEXT, channel_id TEXT,
        order_count INTEGER, units_sold INTEGER, sales_amount DOUBLE PRECISION,
        cost_amount DOUBLE PRECISION, gross_profit DOUBLE PRECISION
    """,
    "fact_inventory_daily": """
        sale_date DATE NOT NULL, store_id TEXT, product_id TEXT,
        on_hand_units INTEGER, inventory_cost_value DOUBLE PRECISION,
        stockout_flag BOOLEAN
    """,
    "fact_traffic_daily": """
        sale_date DATE NOT NULL, store_id TEXT, channel_id TEXT,
        visitor_count INTEGER
    """,
}

CSV_FILES = {name: "%s.csv" % name for name in TABLE_DEFINITIONS}


def create_schema(connection: Any) -> None:
    with connection.cursor() as cursor:
        for name, columns in TABLE_DEFINITIONS.items():
            cursor.execute("CREATE TABLE IF NOT EXISTS %s (%s)" % (name, columns))
        cursor.execute("""
            CREATE OR REPLACE VIEW v_sales_enriched AS
            SELECT s.sale_date, s.store_id, st.store_name, st.region_id, st.region_name,
                   st.city_name, s.product_id, p.product_name, p.category_name,
                   p.subcategory_name, p.brand_name, s.channel_id, c.channel_name,
                   s.order_count, s.units_sold, s.sales_amount, s.cost_amount, s.gross_profit
            FROM fact_sales_daily s
            JOIN dim_store st USING (store_id)
            JOIN dim_product p USING (product_id)
            JOIN dim_channel c USING (channel_id)
        """)
        cursor.execute("""
            CREATE OR REPLACE VIEW v_inventory_enriched AS
            SELECT i.*, st.store_name, st.region_id, st.region_name, st.city_name,
                   p.product_name, p.category_name, p.subcategory_name, p.brand_name
            FROM fact_inventory_daily i
            JOIN dim_store st USING (store_id)
            JOIN dim_product p USING (product_id)
        """)
        cursor.execute("""
            CREATE OR REPLACE VIEW v_traffic_enriched AS
            SELECT t.*, st.store_name, st.region_id, st.region_name, st.city_name,
                   c.channel_name
            FROM fact_traffic_daily t
            JOIN dim_store st USING (store_id)
            JOIN dim_channel c USING (channel_id)
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_date_store ON fact_sales_daily (sale_date, store_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_store ON fact_sales_daily (store_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_product ON fact_sales_daily (product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_channel ON fact_sales_daily (channel_id)")


def seed_csv(connection: Any, data_dir: Path) -> None:
    with connection.cursor() as cursor:
        for table, filename in CSV_FILES.items():
            path = data_dir / filename
            if not path.exists():
                raise FileNotFoundError("找不到种子数据：%s" % path)
            cursor.execute("TRUNCATE TABLE %s" % table)
            with path.open("r", encoding="utf-8", newline="") as handle:
                with cursor.copy("COPY %s FROM STDIN WITH (FORMAT CSV, HEADER TRUE)" % table) as copy:
                    for chunk in iter(lambda: handle.read(1024 * 1024), ""):
                        if chunk:
                            copy.write(chunk)
        connection.commit()


def validation(connection: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in TABLE_DEFINITIONS:
            cursor.execute("SELECT COUNT(*) FROM %s" % table)
            result[table] = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM v_sales_enriched")
        result["v_sales_enriched"] = int(cursor.fetchone()[0])
    return result
