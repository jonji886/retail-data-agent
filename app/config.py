"""应用运行配置与轻量环境文件加载。

配置集中在这里，避免 Agent、Skill、API 和 Demo 各自读取一套环境变量。
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: Path) -> None:
    """加载简单 ``.env`` 文件，不覆盖已有进程环境变量。"""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        try:
            value = shlex.split(raw_value, comments=True)[0] if raw_value.strip() else ""
        except ValueError:
            value = raw_value.strip().strip("\"'")
        os.environ[key] = value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("%s 必须是正整数" % name) from exc
    if value <= 0:
        raise RuntimeError("%s 必须是正整数" % name)
    return value


def _env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量，并对非法值给出明确错误。"""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError("%s 必须是 true/false" % name)


_CHECKPOINT_NODES = {
    "parse_request", "policy_check", "execute_skill", "validate_result",
    "generate_answer", "audit", "unsupported_response", "permission_denied",
    "error_response",
}


@dataclass(frozen=True)
class CheckpointConfig:
    """LangGraph Checkpoint 与 Demo 故障注入配置。

    该配置只描述基础设施行为；Agent 节点不直接读取 SQLite 配置。
    """

    enabled: bool = True
    backend: str = "memory"
    db_path: Path = Path("data/checkpoints.db")
    failure_injection_enabled: bool = False
    fail_after_node: str = ""

    @classmethod
    def from_env(cls, root: Path) -> "CheckpointConfig":
        load_env_file(root / ".env")
        enabled = _env_bool("CHECKPOINT_ENABLED", True)
        backend = os.getenv("CHECKPOINT_BACKEND", "memory").strip().lower() or "memory"
        if backend not in {"memory", "sqlite"}:
            raise RuntimeError("CHECKPOINT_BACKEND 仅支持 memory 或 sqlite")

        db_path = Path(os.getenv("CHECKPOINT_DB_PATH", "data/checkpoints.db"))
        if not db_path.is_absolute():
            db_path = root / db_path

        failure_enabled = _env_bool("FAILURE_INJECTION_ENABLED", False)
        fail_after_node = os.getenv("FAIL_AFTER_NODE", "").strip()
        if failure_enabled and not enabled:
            raise RuntimeError("FAILURE_INJECTION_ENABLED=true 时必须启用 Checkpoint")
        if failure_enabled and fail_after_node not in _CHECKPOINT_NODES:
            raise RuntimeError(
                "FAIL_AFTER_NODE 必须是图节点之一：%s" % ", ".join(sorted(_CHECKPOINT_NODES))
            )

        return cls(
            enabled=enabled,
            backend=backend,
            db_path=db_path,
            failure_injection_enabled=failure_enabled,
            fail_after_node=fail_after_node,
        )


@dataclass(frozen=True)
class DataSourceConfig:
    """数据源运行配置。"""

    kind: str = "duckdb"
    duckdb_path: Path = Path("data/retail.duckdb")
    database_url: str = ""
    pool_size: int = 5
    connect_timeout: float = 5.0
    statement_timeout_ms: int = 10000

    @classmethod
    def from_env(cls, root: Path) -> "DataSourceConfig":
        load_env_file(root / ".env")
        kind = os.getenv("DATA_SOURCE", "duckdb").strip().lower() or "duckdb"
        if kind not in {"duckdb", "postgresql", "postgres"}:
            raise RuntimeError("DATA_SOURCE 仅支持 duckdb 或 postgresql")
        raw_timeout = os.getenv("DB_CONNECT_TIMEOUT", "5")
        try:
            connect_timeout = float(raw_timeout)
        except ValueError as exc:
            raise RuntimeError("DB_CONNECT_TIMEOUT 必须是数字") from exc
        if connect_timeout <= 0:
            raise RuntimeError("DB_CONNECT_TIMEOUT 必须大于 0")
        statement_timeout = _positive_int("DB_STATEMENT_TIMEOUT", 10000)
        database_url = os.getenv("DATABASE_URL", "").strip()
        if kind in {"postgresql", "postgres"} and not database_url:
            raise RuntimeError("DATA_SOURCE=postgresql 时必须配置 DATABASE_URL")
        duckdb_path = Path(os.getenv("DUCKDB_PATH", "data/retail.duckdb"))
        if not duckdb_path.is_absolute():
            duckdb_path = root / duckdb_path
        return cls(
            kind="postgresql" if kind == "postgres" else kind,
            duckdb_path=duckdb_path,
            database_url=database_url,
            pool_size=_positive_int("DB_POOL_SIZE", 5),
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout,
        )
