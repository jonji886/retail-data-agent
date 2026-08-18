"""零售经营分析 Data Agent 本地 Web Demo。"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.graph import run_agent
from app.agent.llm_nlq import DeepSeekNLQEngine
from app.agent.nlq import NLQError, NaturalLanguageQueryEngine
from app.analytics.anomaly import SalesAnomalyDetector
from app.analytics.attribution import SalesAttributor
from app.quality.audit import AuditLogger
from app.quality.evaluation import run_golden
from app.reporting.weekly_report import RetailReportBuilder


st.set_page_config(page_title="优选生活 · Data Agent", page_icon="📊", layout="wide")


@st.cache_resource
def deterministic_engine() -> NaturalLanguageQueryEngine:
    return NaturalLanguageQueryEngine(ROOT)


@st.cache_resource
def report_builder() -> RetailReportBuilder:
    return RetailReportBuilder(ROOT)


def money(value: float) -> str:
    return "¥%s" % format(value, ",.2f")


def percent(value: Any) -> str:
    if value is None:
        return "N/A"
    return "%.2f%%" % (float(value) * 100)


def selected_region(settings: Dict[str, str]):
    return None if settings["region"] == "全部区域" else settings["region"]


def render_sidebar() -> Dict[str, str]:
    st.sidebar.title("优选生活")
    st.sidebar.caption("零售经营分析 Data Agent")
    st.sidebar.divider()
    month = st.sidebar.selectbox("分析月份", ["2025-11", "2025-10", "2025-09", "2025-08"], index=0)
    region = st.sidebar.selectbox("分析范围", ["华东", "华南", "华北", "西南", "全部区域"], index=0)
    dimension = st.sidebar.selectbox("归因维度", ["store_name", "city_name", "category_name", "brand_name", "channel_name"], index=0)
    st.sidebar.divider()
    st.sidebar.info("数据范围：2024～2025 年虚拟零售数据\n\n模型只生成查询计划或报告文字，SQL 和指标计算由本地逻辑完成。")
    return {"month": month, "region": region, "dimension": dimension}


def render_overview(settings: Dict[str, str]) -> None:
    context = report_builder().build_context(settings["month"], selected_region(settings), settings["dimension"])
    st.subheader("经营总览")
    st.caption("%s · %s · 对比 %s" % (context.scope, context.period, context.comparison_period))
    cols = st.columns(4)
    for column, kpi in zip(cols, context.kpis):
        column.metric(kpi.display_name, money(kpi.current_value) if kpi.format == "currency" else format(kpi.current_value, ",.0f"), percent(kpi.change_rate))

    st.markdown("### 销售趋势")
    trend = {item["period"]: item["sales_amount"] for item in context.trend}
    st.line_chart(trend, y_label="销售额", x_label="月份")
    st.dataframe(context.trend, width="stretch", hide_index=True)

    st.markdown("### 当前预警")
    if context.anomalies:
        st.dataframe([
            {"等级": item.severity.upper(), "对象": item.entity_name, "当前销售额": money(item.current_value), "基线": money(item.baseline_value), "变化率": percent(item.change_rate)}
            for item in context.anomalies
        ], width="stretch", hide_index=True)
    else:
        st.success("当前范围内没有触发销售下降预警。")


def render_ask() -> None:
    st.subheader("自然语言问数")
    st.caption("先由模型或规则识别查询计划，再由语义层生成只读 SQL。")
    examples = [
        "2025年11月华东区域销售额同比变化",
        "本月各区域销售额",
        "过去6个月各区域毛利率趋势",
        "上个月按渠道统计订单数",
    ]
    question = st.text_input("请输入经营问题", value=examples[0])
    mode = st.radio("解析模式", ["确定性基线", "DeepSeek-V4-Flash"], horizontal=True)
    logger = AuditLogger(ROOT)
    if st.button("开始分析", type="primary"):
        try:
            if mode == "DeepSeek-V4-Flash":
                answer = DeepSeekNLQEngine(ROOT).answer(question)
            else:
                answer = deterministic_engine().answer(question)
            audit_id = logger.record_query(question, mode, "success", answer.parsed, answer.sql, len(answer.rows))
            st.session_state["last_answer"] = answer
            st.session_state["last_audit_id"] = audit_id
            st.session_state["last_question"] = question
        except (NLQError, RuntimeError, ValueError) as exc:
            logger.record_query(question, mode, "failed", error=str(exc))
            st.error("暂时无法回答：%s" % exc)

    answer = st.session_state.get("last_answer")
    if answer:
        parsed = answer.parsed
        st.success("分析完成")
        st.write("**解析结果：** 指标 `%s` · 维度 `%s` · 过滤 `%s` · 时间 `%s` · 对比 `%s`" % (
            parsed.metric.display_name, parsed.dimensions or "整体", dict(parsed.filters) or "无", parsed.date_range.label, parsed.comparison or "无"
        ))
        st.info(answer.explanation)
        st.dataframe(answer.rows, width="stretch", hide_index=True)
        with st.expander("查看 SQL 与审计信息"):
            st.code(answer.sql, language="sql")
            if answer.comparison_sql:
                st.code(answer.comparison_sql, language="sql")
            st.write("指标口径：", parsed.metric.description)
            st.caption("审计 ID：%s" % st.session_state.get("last_audit_id", "N/A"))
        with st.form("badcase_form"):
            st.markdown("#### 质量反馈")
            reason = st.text_input("如果回答有问题，请说明原因", placeholder="例如：指标口径不符合预期")
            expected = st.text_area("期望结果（可选）")
            if st.form_submit_button("记录为 Badcase"):
                badcase_id = logger.record_badcase(st.session_state.get("last_audit_id", ""), st.session_state.get("last_question", question), reason, expected)
                st.warning("Badcase 已记录：%s" % badcase_id)

    st.markdown("### 推荐问题")
    for item in examples:
        st.markdown("- %s" % item)


def render_alerts(settings: Dict[str, str]) -> None:
    st.subheader("预警与归因")
    detector = SalesAnomalyDetector(ROOT / "data" / "retail.duckdb")
    anomalies = detector.detect(settings["month"], entity_level="region", region_name=selected_region(settings))
    if anomalies:
        for item in anomalies:
            st.warning("[%s] %s：销售额 %s，基线 %s，变化率 %s。规则：%s" % (
                item.severity.upper(), item.entity_name, money(item.current_value), money(item.baseline_value), percent(item.change_rate), item.rule
            ))
    else:
        st.success("当前没有触发销售下降预警。")

    result = SalesAttributor(ROOT / "data" / "retail.duckdb").analyze(
        settings["month"], settings["dimension"], None if settings["region"] == "全部区域" else settings["region"]
    )
    st.markdown("### 销售变化归因")
    st.write("**范围：** %s · **变化额：** %s" % (result.scope, money(result.total_delta)))
    st.dataframe([
        {"成员": item.member, "当前值": money(item.current_value), "对比值": money(item.comparison_value), "变化额": money(item.delta), "贡献率": percent(item.contribution_rate)}
        for item in sorted(result.contributions, key=lambda value: value.delta)
    ], width="stretch", hide_index=True)
    st.caption("贡献率表示数据变化贡献，不等同于已验证的业务因果。")


def render_report(settings: Dict[str, str]) -> None:
    st.subheader("智能经营报告")
    use_llm = st.checkbox("使用 DeepSeek 生成报告文字", value=False)
    if use_llm:
        st.info("报告会先汇总本地数据，再调用 DeepSeek 组织文字，通常需要 10～60 秒；请保持页面打开。")
    else:
        st.caption("确定性报告只使用本地数据，通常几秒内完成。")
    if st.button("生成报告", type="primary"):
        started_at = time.monotonic()
        try:
            with st.status("正在生成报告，请稍候…", expanded=True) as status:
                status.write("1/2 正在汇总 KPI、趋势、预警和归因数据…")
                context = report_builder().build_context(settings["month"], selected_region(settings), settings["dimension"])
                if use_llm:
                    status.write("2/2 正在调用 DeepSeek 组织报告文字…")
                    from app.llm.deepseek_client import DeepSeekClient, DeepSeekConfig
                    report = RetailReportBuilder.to_deepseek_markdown(context, DeepSeekClient(DeepSeekConfig.from_env(ROOT)))
                else:
                    status.write("2/2 正在生成确定性 Markdown 报告…")
                    report = RetailReportBuilder.to_markdown(context)
                st.session_state["report"] = report
                elapsed = time.monotonic() - started_at
                status.update(label="报告生成完成（%.1f 秒）" % elapsed, state="complete", expanded=False)
        except Exception as exc:
            elapsed = time.monotonic() - started_at
            st.error("报告生成失败（耗时 %.1f 秒）。请检查网络、DeepSeek API Key 或稍后重试。错误类型：%s" % (elapsed, type(exc).__name__))
    if st.session_state.get("report"):
        st.download_button("下载 Markdown", st.session_state["report"], file_name="%s-%s.md" % (settings["month"], settings["region"]))
        st.markdown(st.session_state["report"])


def render_agent() -> None:
    st.subheader("Agent")
    st.caption("输入经营问题，Agent 自动识别意图并编排 Skill 与 Tool 执行。")
    examples = [
        "华东区域 2025 年 11 月销售额是多少？环比怎么样？",
        "为什么华东区域 11 月销售额下降了？",
        "2025年11月有哪些销售异常？",
        "生成 2025年11月 华东 经营分析报告",
        "过去6个月各区域销售额趋势",
    ]
    question = st.text_input("请输入经营问题", value=examples[1])
    cols = st.columns(3)
    user_options = {
        "总部经理 (user_hq)": ("user_hq", "hq_manager", {"scope": "all"}),
        "华东区域经理 (user_east)": ("user_east", "region_manager", {"scope": "region", "region_name": "华东"}),
        "门店经理 (user_store_01)": ("user_store_01", "store_manager", {"scope": "store", "store_id": "S001", "store_name": "上海旗舰店1店"}),
    }
    user_label = cols[0].selectbox("当前用户（权限）", list(user_options.keys()))
    use_llm = cols[1].checkbox("使用 LLM（DeepSeek）", value=False)
    run_btn = cols[2].button("执行 Agent", type="primary")
    user_id, role, data_scope = user_options[user_label]

    if run_btn:
        with st.status("Agent 执行中…", expanded=True) as status:
            status.write("解析意图 → 权限检查 → 执行 Skill → 校验结果 → 生成回答 → 审计")
            state = run_agent(question, ROOT, user_id=user_id, role=role, data_scope=data_scope, use_llm=use_llm)
            st.session_state["agent_state"] = state
            status.update(label="Agent 执行完成", state="complete", expanded=False)

    state = st.session_state.get("agent_state")
    if state:
        intent = state.get("intent", "")
        perm = state.get("permission_decision", "")
        skill = state.get("current_skill", "")
        error_type = state.get("error_type")
        answer = state.get("answer", "")
        result = state.get("result") or {}

        # 执行过程展示
        st.markdown("### 执行过程")
        steps = []
        if intent:
            steps.append(("Intent", intent, "✓" if intent != "unsupported" else "✗"))
        if perm:
            steps.append(("Permission", perm, "✓" if perm == "allow" else "✗"))
        if skill:
            steps.append(("Skill", skill, "✓"))
        for tc in state.get("tool_calls", []):
            steps.append(("Tool", tc.get("tool", ""), "✓" if tc.get("status") == "success" else "✗"))
        if not error_type:
            steps.append(("Validation", "passed", "✓"))
        if error_type:
            steps.append(("Result", error_type, "✗"))
        elif answer:
            steps.append(("Answer", "generated", "✓"))
        for label, value, mark in steps:
            st.write("%s **%s**：`%s`" % (mark, label, value))

        # 回答
        if answer:
            st.markdown("### 回答")
            st.info(answer)

        # 结果数据
        if result and isinstance(result, dict) and result.get("rows"):
            st.markdown("### 结果数据")
            st.dataframe(result["rows"], width="stretch", hide_index=True)

        # 归因贡献
        if result and result.get("top_negative"):
            st.markdown("### 主要负向贡献因素")
            st.dataframe([
                {"成员": c.get("member"), "变化额": money(c.get("delta", 0)), "贡献率": percent(c.get("contribution_rate"))}
                for c in result["top_negative"]
            ], width="stretch", hide_index=True)
            st.caption(result.get("limitations", ""))

        # 异常
        if result and result.get("anomalies"):
            st.markdown("### 异常预警")
            st.dataframe([
                {"等级": a.get("severity", "").upper(), "对象": a.get("entity_name"),
                 "当前销售额": money(a.get("current_value", 0)), "变化率": percent(a.get("change_rate"))}
                for a in result["anomalies"]
            ], width="stretch", hide_index=True)

        # 报告
        if result and result.get("markdown"):
            st.markdown("### 生成的报告")
            st.download_button("下载 Markdown", result["markdown"],
                               file_name="%s-%s.md" % (result.get("period", "report"), result.get("scope", "all")))
            st.markdown(result["markdown"])

        # SQL 与口径
        with st.expander("查看 SQL、指标口径与 Trace"):
            for tr in state.get("tool_results", []):
                data = tr.get("data") or {}
                if isinstance(data, dict) and data.get("sql"):
                    st.code(data["sql"], language="sql")
                if isinstance(data, dict) and data.get("comparison_sql"):
                    st.code(data["comparison_sql"], language="sql")
            if result.get("metric_definition"):
                st.write("指标口径：", result["metric_definition"])
            trace_events = state.get("trace_events", [])
            if trace_events:
                st.write("Trace 事件：")
                st.dataframe([
                    {"节点": e.get("node"), "状态": e.get("status", ""),
                     "延迟(ms)": e.get("latency_ms", ""), "trace_id": e.get("trace_id", "")}
                    for e in trace_events
                ], width="stretch", hide_index=True)
            st.caption("request_id: %s | trace_id: %s" % (
                state.get("request_id", ""), state.get("trace_id", "")))

    st.markdown("### 推荐问题")
    for item in examples:
        st.markdown("- %s" % item)


def render_quality() -> None:
    st.subheader("质量评测与审计")
    results = run_golden(ROOT)
    passed = sum(1 for item in results if item.passed)
    cols = st.columns(3)
    cols[0].metric("通过率", "%.1f%%" % (passed / len(results) * 100 if results else 0))
    cols[1].metric("通过用例", "%d" % passed)
    cols[2].metric("总用例", "%d" % len(results))
    st.markdown("### Golden Dataset")
    st.dataframe([
        {"用例": item.case_id, "问题": item.question, "结果": "PASS" if item.passed else "FAIL", "返回行数": item.row_count, "错误": "; ".join(item.errors)}
        for item in results
    ], width="stretch", hide_index=True)

    logger = AuditLogger(ROOT)
    st.markdown("### 最近问数审计")
    audits = logger.recent("query", limit=30)
    if audits:
        st.dataframe([
            {"时间": item.get("timestamp"), "审计 ID": item.get("event_id"), "问题": item.get("question"), "模式": item.get("mode"), "状态": item.get("status"), "结果行数": item.get("row_count")}
            for item in audits
        ], width="stretch", hide_index=True)
    else:
        st.info("尚无问数审计记录。")

    st.markdown("### Badcase")
    badcases = logger.recent("badcase", limit=30)
    if badcases:
        st.dataframe(badcases, width="stretch", hide_index=True)
    else:
        st.info("尚无 Badcase 记录。")


def main() -> None:
    settings = render_sidebar()
    st.title("零售经营分析 Data Agent")
    st.caption("把业务问题转化为可解释、可审计、可复用的经营分析结果")
    overview, agent_tab, ask, alerts, report, quality = st.tabs(
        ["经营总览", "Agent", "自然语言问数", "预警与归因", "智能报告", "质量评测"])
    with overview:
        render_overview(settings)
    with agent_tab:
        render_agent()
    with ask:
        render_ask()
    with alerts:
        render_alerts(settings)
    with report:
        render_report(settings)
    with quality:
        render_quality()


if __name__ == "__main__":
    main()
