"""生成可重复的虚拟零售数据。"""

from __future__ import annotations

import csv
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "generated"
SEED = 20250806


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Dict[str, object]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def dimensions() -> Dict[str, List[Dict[str, object]]]:
    regions = [
        {"region_id": "R01", "region_name": "华东", "region_manager": "陈晨"},
        {"region_id": "R02", "region_name": "华南", "region_manager": "林浩"},
        {"region_id": "R03", "region_name": "华北", "region_manager": "赵敏"},
        {"region_id": "R04", "region_name": "西南", "region_manager": "周宁"},
    ]
    cities = {
        "R01": ["上海", "杭州"],
        "R02": ["广州", "深圳"],
        "R03": ["北京", "天津"],
        "R04": ["成都", "重庆"],
    }
    stores: List[Dict[str, object]] = []
    store_number = 1
    store_types = ["旗舰店", "标准店"]
    for region in regions:
        for city in cities[str(region["region_id"])]:
            for suffix in range(2):
                stores.append(
                    {
                        "store_id": "S%03d" % store_number,
                        "store_name": "%s%s%s店" % (city, store_types[suffix], store_number),
                        "region_id": region["region_id"],
                        "region_name": region["region_name"],
                        "city_name": city,
                        "store_type": store_types[suffix],
                        "opening_date": "2022-01-01" if suffix == 0 else "2023-06-01",
                    }
                )
                store_number += 1

    categories = [
        ("C01", "食品", ["休闲食品", "粮油调味"]),
        ("C02", "饮料", ["饮用水", "即饮饮料"]),
        ("C03", "日化", ["清洁用品", "个人护理"]),
        ("C04", "家居", ["厨房用品", "家纺用品"]),
        ("C05", "数码", ["手机配件", "智能设备"]),
        ("C06", "生鲜", ["水果蔬菜", "肉禽蛋品"]),
    ]
    products: List[Dict[str, object]] = []
    product_number = 1
    for category_id, category_name, subcategories in categories:
        for sub_index, subcategory_name in enumerate(subcategories):
            for item_index in range(4):
                products.append(
                    {
                        "product_id": "P%04d" % product_number,
                        "product_name": "%s%s%d" % (subcategory_name, "精选商品", item_index + 1),
                        "category_id": category_id,
                        "category_name": category_name,
                        "subcategory_name": subcategory_name,
                        "brand_name": ["优选", "鲜活", "悦享", "家宜"][item_index],
                        "unit_cost": round(8 + product_number * 0.7 + sub_index * 2, 2),
                        "unit_price": round((8 + product_number * 0.7 + sub_index * 2) * (1.25 + item_index * 0.04), 2),
                    }
                )
                product_number += 1

    channels = [
        {"channel_id": "CH01", "channel_name": "线下门店", "channel_type": "offline"},
        {"channel_id": "CH02", "channel_name": "官网", "channel_type": "online"},
        {"channel_id": "CH03", "channel_name": "小程序", "channel_type": "online"},
        {"channel_id": "CH04", "channel_name": "第三方电商", "channel_type": "online"},
    ]
    dates = []
    holidays = {"2025-01-01", "2025-02-01", "2025-05-01", "2025-10-01"}
    for current in daterange(date(2024, 1, 1), date(2025, 12, 31)):
        dates.append(
            {
                "date_key": current.isoformat(),
                "year": current.year,
                "quarter": "Q%d" % ((current.month - 1) // 3 + 1),
                "month": current.month,
                "month_name": "%d月" % current.month,
                "week_of_year": current.isocalendar()[1],
                "day_of_week": current.weekday() + 1,
                "is_weekend": current.weekday() >= 5,
                "is_holiday": current.isoformat() in holidays,
            }
        )
    return {"regions": regions, "stores": stores, "products": products, "channels": channels, "dates": dates}


def fact_sales(data: Dict[str, List[Dict[str, object]]]) -> Iterable[Dict[str, object]]:
    rng = random.Random(SEED)
    for day in data["dates"]:
        month = int(day["month"])
        year = int(day["year"])
        date_key = str(day["date_key"])
        seasonal = 1.0 + 0.12 * math.sin((month - 1) / 12 * math.pi * 2)
        year_factor = 0.90 if year == 2024 else 1.0
        holiday_factor = 1.18 if bool(day["is_holiday"]) else 1.0
        weekend_factor = 1.12 if bool(day["is_weekend"]) else 1.0
        promo_factor = 1.22 if month in (3, 6, 11) else 1.0
        for store in data["stores"]:
            region_factor = 1.0 + (int(str(store["store_id"])[1:]) % 5) * 0.06
            # 刻意植入华东 11 月异常，供后续预警和归因验证。
            anomaly_factor = 0.62 if str(store["region_id"]) == "R01" and year == 2025 and month == 11 else 1.0
            for product in data["products"]:
                product_factor = 0.75 + (int(str(product["product_id"])[1:]) % 7) * 0.08
                for channel in data["channels"]:
                    channel_factor = {"CH01": 1.0, "CH02": 0.38, "CH03": 0.48, "CH04": 0.62}[str(channel["channel_id"])]
                    noise = rng.uniform(0.85, 1.15)
                    base_orders = 1.6 * year_factor * seasonal * holiday_factor * weekend_factor * promo_factor
                    orders = max(0, int(round(base_orders * region_factor * product_factor * channel_factor * anomaly_factor * noise)))
                    units = orders * (1 + (int(str(product["product_id"])[1:]) % 3))
                    sales = units * float(product["unit_price"])
                    cost = units * float(product["unit_cost"])
                    yield {
                        "sale_date": date_key,
                        "store_id": store["store_id"],
                        "product_id": product["product_id"],
                        "channel_id": channel["channel_id"],
                        "order_count": orders,
                        "units_sold": units,
                        "sales_amount": round(sales, 2),
                        "cost_amount": round(cost, 2),
                        "gross_profit": round(sales - cost, 2),
                    }


def fact_inventory(data: Dict[str, List[Dict[str, object]]]) -> Iterable[Dict[str, object]]:
    rng = random.Random(SEED + 1)
    for day in data["dates"]:
        month = int(day["month"])
        year = int(day["year"])
        for store in data["stores"]:
            for product in data["products"]:
                base = 35 + (int(str(product["product_id"])[1:]) % 11) * 4
                seasonal = 1.25 if month in (1, 6, 11, 12) else 1.0
                stockout = (int(str(store["store_id"])[1:]) % 7 == 0 and int(str(product["product_id"])[1:]) % 9 == 0 and year == 2025 and month == 11)
                units = 0 if stockout else max(0, int(round(base * seasonal * rng.uniform(0.75, 1.35))))
                yield {
                    "sale_date": day["date_key"],
                    "store_id": store["store_id"],
                    "product_id": product["product_id"],
                    "on_hand_units": units,
                    "inventory_cost_value": round(units * float(product["unit_cost"]), 2),
                    "stockout_flag": stockout,
                }


def fact_traffic(data: Dict[str, List[Dict[str, object]]]) -> Iterable[Dict[str, object]]:
    rng = random.Random(SEED + 2)
    for day in data["dates"]:
        weekend_factor = 1.25 if bool(day["is_weekend"]) else 1.0
        for store in data["stores"]:
            for channel in data["channels"]:
                channel_base = {"CH01": 240, "CH02": 160, "CH03": 210, "CH04": 280}[str(channel["channel_id"])]
                store_factor = 1.0 + (int(str(store["store_id"])[1:]) % 4) * 0.1
                visitors = int(round(channel_base * weekend_factor * store_factor * rng.uniform(0.8, 1.2)))
                yield {"sale_date": day["date_key"], "store_id": store["store_id"], "channel_id": channel["channel_id"], "visitor_count": visitors}


def main() -> None:
    data = dimensions()
    files = {
        "dim_date.csv": (["date_key", "year", "quarter", "month", "month_name", "week_of_year", "day_of_week", "is_weekend", "is_holiday"], data["dates"]),
        "dim_region.csv": (["region_id", "region_name", "region_manager"], data["regions"]),
        "dim_store.csv": (["store_id", "store_name", "region_id", "region_name", "city_name", "store_type", "opening_date"], data["stores"]),
        "dim_product.csv": (["product_id", "product_name", "category_id", "category_name", "subcategory_name", "brand_name", "unit_cost", "unit_price"], data["products"]),
        "dim_channel.csv": (["channel_id", "channel_name", "channel_type"], data["channels"]),
        "fact_sales_daily.csv": (["sale_date", "store_id", "product_id", "channel_id", "order_count", "units_sold", "sales_amount", "cost_amount", "gross_profit"], fact_sales(data)),
        "fact_inventory_daily.csv": (["sale_date", "store_id", "product_id", "on_hand_units", "inventory_cost_value", "stockout_flag"], fact_inventory(data)),
        "fact_traffic_daily.csv": (["sale_date", "store_id", "channel_id", "visitor_count"], fact_traffic(data)),
    }
    print("Generating virtual retail data...")
    for filename, (fields, rows) in files.items():
        count = write_csv(OUTPUT_DIR / filename, fields, rows)
        print("  %-26s %8d rows" % (filename, count))


if __name__ == "__main__":
    sys.exit(main())
