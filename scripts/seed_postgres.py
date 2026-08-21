"""仅重新导入固定 Demo 数据（不会修改表结构）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DataSourceConfig, load_env_file
from scripts.postgres_schema import seed_csv, validation


def main() -> None:
    load_env_file(ROOT / ".env")
    import psycopg
    config = DataSourceConfig.from_env(ROOT)
    if config.kind != "postgresql":
        raise SystemExit("请设置 DATA_SOURCE=postgresql 并配置 DATABASE_URL")
    with psycopg.connect(config.database_url, connect_timeout=config.connect_timeout) as connection:
        seed_csv(connection, ROOT / "data" / "generated")
        print("PostgreSQL seed completed: %s" % validation(connection))


if __name__ == "__main__":
    main()
