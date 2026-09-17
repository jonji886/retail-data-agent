"""创建 LangGraph 官方 Checkpointer。

业务节点只接收 Agent State 和运行时 context，不感知 SQLite 连接或数据库表。
"""

from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import CheckpointConfig


@contextmanager
def checkpoint_session(
    root: Path,
    config: Optional[CheckpointConfig] = None,
) -> Iterator[Optional[BaseCheckpointSaver]]:
    """创建一个 Graph 生命周期内使用的 Checkpointer。

    SQLite 连接由本次 Graph 调用拥有，进程重启后通过同一 db_path 重新打开；
    实际的 checkpoint schema 和读写均由 LangGraph 的 SqliteSaver 负责。
    """
    selected = config or CheckpointConfig.from_env(root)
    if not selected.enabled:
        yield None
        return

    if selected.backend == "memory":
        yield InMemorySaver()
        return

    if selected.backend != "sqlite":  # pragma: no cover - from_env 已校验
        raise ValueError("不支持的 Checkpoint backend: %s" % selected.backend)

    selected.db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(selected.db_path), check_same_thread=False)) as conn:
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver
