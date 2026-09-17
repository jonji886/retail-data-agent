"""Durable Checkpoint、线程隔离与跨进程恢复回归。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from app.agent.graph import inspect_checkpoint, resume_agent, run_agent
from app.config import CheckpointConfig


ROOT = Path(__file__).resolve().parents[1]


def sqlite_config(path: Path, *, interrupt: bool = False) -> CheckpointConfig:
    return CheckpointConfig(
        enabled=True,
        backend="sqlite",
        db_path=path,
        failure_injection_enabled=interrupt,
        fail_after_node="execute_skill" if interrupt else "",
    )


class DurableCheckpointTest(unittest.TestCase):
    def test_sqlite_persistence_and_resume_use_new_graph_instance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "checkpoints.db"
            first = run_agent(
                "2025年11月华东区域销售额同比变化",
                ROOT,
                thread_id="durable-test",
                checkpoint_config=sqlite_config(db_path, interrupt=True),
            )
            self.assertTrue(db_path.exists())
            before = inspect_checkpoint(ROOT, "durable-test", sqlite_config(db_path))
            self.assertEqual(before["status"], "paused")
            self.assertEqual(before["next_nodes"], ["validate_result"])
            self.assertIn("query_plan", before["state"])
            self.assertIn("result", before["state"])
            self.assertNotIn("_data_source", before["state"])
            self.assertEqual(_nodes(first), ["parse_request", "policy_check", "execute_skill"])

            # resume_agent 会重新打开 DB、重新创建并编译 Graph，再用 None input 恢复。
            final = resume_agent(ROOT, "durable-test", checkpoint_config=sqlite_config(db_path))
            self.assertIsNone(final.get("error_type"))
            self.assertIn("answer", final)
            self.assertEqual(
                Counter(_nodes(final)),
                Counter({
                    "parse_request": 1,
                    "policy_check": 1,
                    "execute_skill": 1,
                    "validate_result": 1,
                    "generate_answer": 1,
                    "audit_run": 1,
                }),
            )
            after = inspect_checkpoint(ROOT, "durable-test", sqlite_config(db_path))
            self.assertEqual(after["status"], "completed")
            self.assertEqual(after["next_nodes"], [])
            self.assertNotIn("_data_source", after["state"])

    def test_thread_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = sqlite_config(Path(directory) / "checkpoints.db")
            run_agent("2025年11月华东区域销售额", ROOT, thread_id="thread-A", checkpoint_config=config)
            run_agent("2025年11月华南区域销售额", ROOT, thread_id="thread-B", checkpoint_config=config)

            state_a = inspect_checkpoint(ROOT, "thread-A", config)["state"]
            state_b = inspect_checkpoint(ROOT, "thread-B", config)["state"]
            self.assertEqual(state_a["thread_id"], "thread-A")
            self.assertEqual(state_b["thread_id"], "thread-B")
            self.assertEqual(state_a["query_plan"]["filters"]["region_name"], "华东")
            self.assertEqual(state_b["query_plan"]["filters"]["region_name"], "华南")

    def test_completed_thread_resume_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = sqlite_config(Path(directory) / "checkpoints.db")
            original = run_agent(
                "2025年11月华东区域销售额",
                ROOT,
                thread_id="completed-test",
                checkpoint_config=config,
            )
            before = inspect_checkpoint(ROOT, "completed-test", config)
            resumed = resume_agent(ROOT, "completed-test", checkpoint_config=config)
            after = inspect_checkpoint(ROOT, "completed-test", config)
            self.assertEqual(before["status"], "completed")
            self.assertEqual(before["checkpoint_count"], after["checkpoint_count"])
            self.assertEqual(_nodes(original), _nodes(resumed))

    def test_memory_backend_remains_available(self) -> None:
        state = run_agent(
            "2025年11月华东区域销售额",
            ROOT,
            thread_id="memory-test",
            checkpoint_config=CheckpointConfig(enabled=True, backend="memory"),
        )
        self.assertEqual(state["intent"], "metric_query")
        self.assertIsNone(state.get("error_type"))

    def test_cli_recovers_in_a_new_python_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "process-checkpoints.db"
            env = os.environ.copy()
            env.update({
                "DATA_SOURCE": "duckdb",
                "DUCKDB_PATH": "data/retail.duckdb",
                "PYTHONPATH": str(ROOT),
            })
            command = [sys.executable, "-m", "scripts.checkpoint_demo"]
            start = subprocess.run(
                command + [
                    "start", "--thread-id", "process-test", "--root", str(ROOT),
                    "--db-path", str(db_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
            self.assertIn("Next node: validate_result", start.stdout)

            resume = subprocess.run(
                command + [
                    "resume", "--thread-id", "process-test", "--root", str(ROOT),
                    "--db-path", str(db_path),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(resume.returncode, 0, resume.stdout + resume.stderr)
            self.assertIn("Resume from: validate_result", resume.stdout)
            self.assertIn("Task completed: yes", resume.stdout)


def _nodes(state: dict) -> list[str]:
    return [str(event["node"]) for event in state.get("trace_events", [])]


if __name__ == "__main__":
    unittest.main()
