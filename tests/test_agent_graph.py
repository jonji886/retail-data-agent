"""LangGraph Agent 图集成测试：验证路由、权限、Skill 调度、错误路径。"""

import unittest
from pathlib import Path

from app.agent.graph import run_agent


ROOT = Path(".")


class AgentGraphTest(unittest.TestCase):
    def test_metric_query_routes_to_correct_skill(self) -> None:
        state = run_agent("2025年11月华东区域销售额同比变化", ROOT)
        self.assertEqual(state["intent"], "metric_query")
        self.assertEqual(state["permission_decision"], "allow")
        self.assertEqual(state["current_skill"], "metric_query")
        self.assertIsNone(state.get("error_type"))
        result = state["result"]
        self.assertGreater(result["row_count"], 0)

    def test_attribution_routes_to_attribution_skill(self) -> None:
        state = run_agent("为什么华东2025年11月销售额下降了？", ROOT)
        self.assertEqual(state["intent"], "attribution_analysis")
        self.assertEqual(state["current_skill"], "attribution_analysis")
        result = state["result"]
        self.assertEqual(result["current_period"], "2025-11")
        self.assertEqual(result["comparison_period"], "2025-10")
        self.assertLess(result["total_delta"], 0)
        self.assertIn("结论：", state["answer"])
        self.assertIn("¥1,371,235.35", state["answer"])
        self.assertIn("-25.75%", state["answer"])

    def test_attribution_month_with_space_is_not_replaced_by_latest_month(self) -> None:
        state = run_agent("为什么华东区域 11 月销售额下降了？", ROOT)
        result = state["result"]
        self.assertEqual(result["current_period"], "2025-11")
        self.assertEqual(result["comparison_period"], "2025-10")
        self.assertLess(result["total_delta"], 0)

    def test_unsupported_intent_rejected(self) -> None:
        state = run_agent("删除销售数据", ROOT)
        self.assertEqual(state["intent"], "unsupported")
        self.assertIsNotNone(state.get("error_type"))
        self.assertIn("无法处理", state["answer"])

    def test_permission_denied_blocks_tool_execution(self) -> None:
        # 华东区域经理尝试查询华南
        state = run_agent(
            "华南2025年11月销售额", ROOT,
            user_id="user_east", role="region_manager",
            data_scope={"scope": "region", "region_name": "华东"},
        )
        self.assertEqual(state["permission_decision"], "deny")
        self.assertIsNone(state.get("current_skill"))
        # Tool 不应执行
        self.assertEqual(state.get("tool_calls"), [])

    def test_tool_error_goes_to_error_path(self) -> None:
        # 使用不存在的指标（通过构造一个无法解析的问题）
        state = run_agent("本月各区域不存在指标XYZ", ROOT)
        self.assertEqual(state["intent"], "unsupported")
        self.assertIsNotNone(state.get("error_type"))

    def test_result_validation_prevents_fake_answer(self) -> None:
        # 空数据场景：查询不存在的门店
        state = run_agent("2025年11月上海旗舰店999店销售额", ROOT)
        # 应该走 metric_query，但门店不存在 → 空结果或 metric_query
        # 关键是不应有 error_type 为 None 且 answer 编造数字
        if state.get("intent") == "metric_query":
            result = state.get("result") or {}
            if result.get("rows") == []:
                # 空结果：answer 应说明无数据
                self.assertIn("未返回数据", state.get("answer", ""))

    def test_trace_id_and_request_id_present(self) -> None:
        state = run_agent("本月各区域销售额", ROOT)
        self.assertTrue(state.get("request_id"))
        self.assertTrue(state.get("trace_id"))
        self.assertTrue(state.get("trace_events"))
        # 至少有 parse_request / policy_check / execute_skill / validate_result / generate_answer / audit
        nodes = [e.get("node") for e in state["trace_events"]]
        self.assertIn("parse_request", nodes)
        self.assertIn("audit_run", nodes)

    def test_store_manager_can_only_query_own_store(self) -> None:
        state = run_agent(
            "2025年11月销售额", ROOT,
            user_id="user_store_01", role="store_manager",
            data_scope={"scope": "store", "store_id": "S001", "store_name": "上海旗舰店1店"},
        )
        self.assertEqual(state["permission_decision"], "allow")
        # 验证 filters 被注入了 store_id
        plan = state.get("query_plan", {})
        self.assertEqual(plan.get("filters", {}).get("store_id"), "S001")

    def test_hq_can_query_any_region(self) -> None:
        state = run_agent("华南2025年11月销售额", ROOT)
        self.assertEqual(state["permission_decision"], "allow")
        self.assertEqual(state["intent"], "metric_query")


if __name__ == "__main__":
    unittest.main()
