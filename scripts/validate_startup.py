"""启动前校验配置、语义层与数据源连接。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import DataSourceConfig, load_env_file
from app.data_sources.factory import create_data_source
from app.semantic_layer.catalog import MetricCatalog


def main() -> None:
    load_env_file(ROOT / ".env")
    MetricCatalog.from_file(ROOT / "configs" / "metrics" / "metrics.json")
    config = DataSourceConfig.from_env(ROOT)
    source = create_data_source(ROOT, config)
    try:
        if not source.health_check():
            raise SystemExit("数据源健康检查失败（kind=%s）" % config.kind)
    finally:
        source.close()
    print("Startup validation passed: datasource=%s" % config.kind)


if __name__ == "__main__":
    main()
