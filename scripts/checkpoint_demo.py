"""SQLite Durable Checkpoint + 跨进程故障恢复 Demo。

用法：
    python3 -m scripts.checkpoint_demo start --thread-id retail-demo-001
    python3 -m scripts.checkpoint_demo resume --thread-id retail-demo-001
    python3 -m scripts.checkpoint_demo inspect --thread-id retail-demo-001
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

from app.agent.graph import inspect_checkpoint, resume_agent, run_agent
from app.config import CheckpointConfig


DEFAULT_QUESTION = "2025年11月华东区域销售额同比变化"


def _root(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _checkpoint_config(args: argparse.Namespace, root: Path, *, inject: bool) -> CheckpointConfig:
    base = CheckpointConfig.from_env(root)
    db_path = base.db_path
    if args.db_path:
        db_path = Path(args.db_path).expanduser()
        if not db_path.is_absolute():
            db_path = root / db_path
    return replace(
        base,
        enabled=True,
        backend="sqlite",
        db_path=db_path,
        failure_injection_enabled=inject,
        fail_after_node=args.fail_after_node if inject else "",
    )


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--thread-id", required=True, help="稳定的 LangGraph thread_id")
    parser.add_argument("--root", default=".", help="工程根目录，默认当前目录")
    parser.add_argument("--db-path", default="", help="Checkpoint DB 路径，默认读取 CHECKPOINT_DB_PATH")


def _start(args: argparse.Namespace) -> int:
    root = _root(args.root)
    config = _checkpoint_config(args, root, inject=True)
    state = run_agent(
        args.question,
        root=root,
        thread_id=args.thread_id,
        checkpoint_config=config,
    )
    inspection = inspect_checkpoint(root, args.thread_id, checkpoint_config=config)
    print("Process A: start")
    print("thread_id: %s" % args.thread_id)
    print("Failure injection: interrupt_after=%s" % args.fail_after_node)
    print("Last checkpoint node: %s" % inspection.get("current_node", ""))
    print("Next node: %s" % ", ".join(inspection.get("next_nodes", [])))
    print("Checkpoint count: %s" % inspection.get("checkpoint_count", 0))
    print("Completed nodes: %s" % ", ".join(_trace_nodes(state)))
    if inspection.get("status") != "paused":
        raise SystemExit("Demo start 未停在 Checkpoint：%s" % inspection)
    print("Process A: stopped after the persisted safe checkpoint")
    print("请在新的 shell / Python process 中执行 resume。")
    return 0


def _resume(args: argparse.Namespace) -> int:
    root = _root(args.root)
    config = _checkpoint_config(args, root, inject=False)
    before = inspect_checkpoint(root, args.thread_id, checkpoint_config=config)
    if before.get("status") == "not_found":
        raise SystemExit("Checkpoint not found for thread_id=%s" % args.thread_id)
    print("Checkpoint found")
    print("thread_id: %s" % args.thread_id)
    print("Last checkpoint: %s" % before.get("checkpoint_id", ""))
    print("Resume from: %s" % ", ".join(before.get("next_nodes", [])))
    if before.get("status") == "completed":
        print("Thread %s already completed. Nothing to resume." % args.thread_id)
        return 0

    state = resume_agent(root, args.thread_id, checkpoint_config=config)
    after = inspect_checkpoint(root, args.thread_id, checkpoint_config=config)
    print("Task completed: %s" % ("yes" if after.get("status") == "completed" else "no"))
    print("Current node: %s" % after.get("current_node", ""))
    print("Checkpoint count: %s" % after.get("checkpoint_count", 0))
    print("All trace nodes: %s" % ", ".join(_trace_nodes(state)))
    if after.get("status") != "completed":
        raise SystemExit("Resume 未完成：%s" % after)
    return 0


def _inspect(args: argparse.Namespace) -> int:
    root = _root(args.root)
    config = _checkpoint_config(args, root, inject=False)
    inspection = inspect_checkpoint(root, args.thread_id, checkpoint_config=config)
    print("Thread ID: %s" % inspection["thread_id"])
    print("Status: %s" % inspection.get("status", ""))
    print("Checkpoint ID: %s" % inspection.get("checkpoint_id", ""))
    print("Current node: %s" % inspection.get("current_node", ""))
    print("Next node: %s" % ", ".join(inspection.get("next_nodes", [])))
    print("Updated time: %s" % inspection.get("updated_at", ""))
    print("Checkpoint count: %s" % inspection.get("checkpoint_count", 0))
    print("Checkpoint history:")
    for item in inspection.get("history", []):
        print(
            "  #%s %s -> %s"
            % (item["number"], item["node"], ", ".join(item["next_nodes"]))
        )
    return 0


def _trace_nodes(state: Dict[str, Any]) -> list[str]:
    return [str(event.get("node")) for event in state.get("trace_events", []) if event.get("node")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Retail Data Agent SQLite durable checkpoint demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="执行到指定节点后持久化并退出")
    _add_common(start)
    start.add_argument("--question", default=DEFAULT_QUESTION)
    start.add_argument("--fail-after-node", default="execute_skill")
    start.set_defaults(handler=_start)

    resume = subparsers.add_parser("resume", help="新进程从已有 Checkpoint 继续")
    _add_common(resume)
    resume.add_argument("--fail-after-node", default="execute_skill", help=argparse.SUPPRESS)
    resume.set_defaults(handler=_resume)

    inspect = subparsers.add_parser("inspect", help="查看某个 thread 的状态和历史")
    _add_common(inspect)
    inspect.add_argument("--fail-after-node", default="execute_skill", help=argparse.SUPPRESS)
    inspect.set_defaults(handler=_inspect)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
