"""初始化 PostgreSQL/Supabase：建表 → 导入固定种子 → 索引/视图 → 校验。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_env_file
from app.data_sources.factory import create_data_source
from scripts.postgres_schema import create_schema, seed_csv, validation


def main() -> None:
    load_env_file(ROOT / ".env")
    source = create_data_source(ROOT)
    if source.dialect != "postgresql":
        raise SystemExit("请设置 DATA_SOURCE=postgresql 并配置 DATABASE_URL")
    # 使用数据源内部连接池无法执行 DDL；初始化脚本是唯一允许写数据库的运维入口。
    import psycopg
    from app.config import DataSourceConfig
    config = DataSourceConfig.from_env(ROOT)
    with psycopg.connect(config.database_url, connect_timeout=config.connect_timeout) as connection:
        create_schema(connection)
        seed_csv(connection, ROOT / "data" / "generated")
        counts = validation(connection)
    source.close()
    print("PostgreSQL initialized")
    for table, count in counts.items():
        print("  %-24s %8d rows" % (table, count))


if __name__ == "__main__":
    main()
