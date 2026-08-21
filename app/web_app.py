"""零售经营分析 Data Agent 本地 Web Demo。"""

from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.application import AgentApplicationService
from app.data_sources.factory import create_data_source
from app.agent.llm_nlq import OpenRouterNLQEngine
from app.agent.nlq import NaturalLanguageQueryEngine
from app.llm.openrouter_client import DEFAULT_MODEL, OpenRouterConfig, load_env_file
from app.analytics.anomaly import SalesAnomalyDetector
from app.analytics.attribution import SalesAttributor
from app.quality.audit import AuditLogger
from app.quality.evaluation import run_golden_v2
from app.observability.runtime_logging import log_event, request_log_context
from app.presentation.decision_support import (
    build_attribution_summary,
    build_attribution_table,
    build_follow_up_questions,
)
from app.reporting.weekly_report import RetailReportBuilder


st.set_page_config(page_title="优选生活 · Data Agent", page_icon="📊", layout="wide")


@st.cache_resource
def deterministic_engine() -> NaturalLanguageQueryEngine:
    return NaturalLanguageQueryEngine(ROOT, data_source=app_data_source())


@st.cache_resource
def app_data_source():
    return create_data_source(ROOT)


@st.cache_resource
def agent_service() -> AgentApplicationService:
    return AgentApplicationService(ROOT, data_source=app_data_source())


@st.cache_resource
def report_builder() -> RetailReportBuilder:
    return RetailReportBuilder(ROOT, data_source=app_data_source())


def money(value: float) -> str:
    return "¥%s" % format(value, ",.2f")


def percent(value: Any) -> str:
    if value is None:
        return "N/A"
    return "%.2f%%" % (float(value) * 100)


def selected_region(settings: Dict[str, str]):
    return None if settings["region"] == "全部区域" else settings["region"]


def openrouter_status() -> tuple[bool, str]:
    """返回当前进程看到的 OpenRouter 配置状态，不暴露 API Key。"""
    configured = OpenRouterConfig.is_configured(ROOT)
    load_env_file(ROOT / ".env")
    model = os.getenv("LLM_MODEL", "").strip() or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return configured, model


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
    llm_ready, model = openrouter_status()
    if llm_ready:
        st.caption("OpenRouter 已配置（模型：%s），调用结果仍会经过本地语义层、权限和只读 SQL 校验。" % model)
    else:
        st.info("当前未配置 OpenRouter API Key，仅提供确定性基线。Render 部署请在 Environment 中添加 OPENROUTER_API_KEY 后重新部署。")
    openrouter_mode = "OpenRouter（%s）" % model
    modes = ["确定性基线"] + ([openrouter_mode] if llm_ready else [])
    mode = st.radio("解析模式", modes, horizontal=True)
    logger = AuditLogger(ROOT)
    if st.button("开始分析", type="primary"):
        diagnostic: Dict[str, Any] = {}
        request_started_at = time.monotonic()
        try:
            with request_log_context(
                surface="natural_language_query",
                use_llm=mode == openrouter_mode,
            ) as log_context:
                diagnostic = log_context
                data_source = app_data_source()
                log_event(
                    "natural_language_request_started",
                    question_length=len(question),
                    datasource=data_source.dialect,
                )
                if mode == openrouter_mode:
                    answer = OpenRouterNLQEngine(ROOT, data_source=data_source).answer(question)
                else:
                    answer = deterministic_engine().answer(question)
                log_event(
                    "natural_language_request_completed",
                    row_count=len(answer.rows),
                    latency_ms=int((time.monotonic() - request_started_at) * 1000),
                )
            audit_id = logger.record_query(question, mode, "success", answer.parsed, answer.sql, len(answer.rows))
            st.session_state["last_answer"] = answer
            st.session_state["last_audit_id"] = audit_id
            st.session_state["last_question"] = question
            st.session_state["last_request_id"] = diagnostic.get("request_id", "")
            st.session_state["last_trace_id"] = diagnostic.get("trace_id", "")
        except Exception as exc:  # noqa: BLE001
            log_event(
                "natural_language_request_failed",
                request_id=diagnostic.get("request_id"),
                trace_id=diagnostic.get("trace_id"),
                surface="natural_language_query",
                error_type=type(exc).__name__,
                latency_ms=int((time.monotonic() - request_started_at) * 1000),
            )
            logger.record_query(question, mode, "failed", error=str(exc))
            st.error("暂时无法回答：%s\n诊断编号：%s" % (exc, diagnostic.get("trace_id") or diagnostic.get("request_id", "N/A")))

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
            st.caption("request_id: %s | trace_id: %s" % (
                st.session_state.get("last_request_id", "N/A"),
                st.session_state.get("last_trace_id", "N/A"),
            ))
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
    detector = SalesAnomalyDetector(ROOT / "data" / "retail.duckdb", data_source=app_data_source())
    anomalies = detector.detect(settings["month"], entity_level="region", region_name=selected_region(settings))
    if anomalies:
        for item in anomalies:
            st.warning("[%s] %s：销售额 %s，基线 %s，变化率 %s。规则：%s" % (
                item.severity.upper(), item.entity_name, money(item.current_value), money(item.baseline_value), percent(item.change_rate), item.rule
            ))
    else:
        st.success("当前没有触发销售下降预警。")

    result = SalesAttributor(ROOT / "data" / "retail.duckdb", data_source=app_data_source()).analyze(
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
    llm_ready, model = openrouter_status()
    use_llm = st.checkbox("使用 OpenRouter 生成报告文字", value=llm_ready, disabled=not llm_ready)
    if llm_ready:
        st.caption("已连接 OpenRouter（模型：%s）。报告中的 KPI、趋势和归因数字仍由本地逻辑生成。" % model)
    else:
        st.info("未配置 OPENROUTER_API_KEY，当前只能生成确定性报告。")
    if use_llm:
        st.info("报告会先汇总本地数据，再调用 OpenRouter 组织文字，通常需要 10～60 秒；请保持页面打开。")
    else:
        st.caption("确定性报告只使用本地数据，通常几秒内完成。")
    if st.button("生成报告", type="primary"):
        started_at = time.monotonic()
        diagnostic: Dict[str, Any] = {}
        try:
            with request_log_context(
                surface="report_generation",
                use_llm=use_llm,
            ) as log_context:
                diagnostic = log_context
                data_source = app_data_source()
                log_event("report_request_started", datasource=data_source.dialect)
                with st.status("正在生成报告，请稍候…", expanded=True) as status:
                    status.write("1/2 正在汇总 KPI、趋势、预警和归因数据…")
                    context = report_builder().build_context(settings["month"], selected_region(settings), settings["dimension"])
                    if use_llm:
                        status.write("2/2 正在调用 OpenRouter 组织报告文字…")
                        from app.llm.openrouter_client import OpenRouterClient, OpenRouterConfig
                        report = RetailReportBuilder.to_openrouter_markdown(context, OpenRouterClient(OpenRouterConfig.from_env(ROOT)))
                    else:
                        status.write("2/2 正在生成确定性 Markdown 报告…")
                        report = RetailReportBuilder.to_markdown(context)
                    st.session_state["report"] = report
                    st.session_state["report_request_id"] = diagnostic.get("request_id", "")
                    st.session_state["report_trace_id"] = diagnostic.get("trace_id", "")
                    elapsed = time.monotonic() - started_at
                    log_event("report_request_completed", latency_ms=int(elapsed * 1000))
                    status.update(label="报告生成完成（%.1f 秒）" % elapsed, state="complete", expanded=False)
        except Exception as exc:
            elapsed = time.monotonic() - started_at
            log_event(
                "report_request_failed",
                request_id=diagnostic.get("request_id"),
                trace_id=diagnostic.get("trace_id"),
                surface="report_generation",
                error_type=type(exc).__name__,
                latency_ms=int(elapsed * 1000),
            )
            st.error("报告生成失败（耗时 %.1f 秒）。请检查网络、OpenRouter API Key 或稍后重试。错误类型：%s\n诊断编号：%s" % (
                elapsed, type(exc).__name__, diagnostic.get("trace_id") or diagnostic.get("request_id", "N/A")
            ))
    if st.session_state.get("report"):
        st.caption("request_id: %s | trace_id: %s" % (
            st.session_state.get("report_request_id", "N/A"),
            st.session_state.get("report_trace_id", "N/A"),
        ))
        st.download_button("下载 Markdown", st.session_state["report"], file_name="%s-%s.md" % (settings["month"], settings["region"]))
        st.markdown(st.session_state["report"])


def _render_attribution_business_view(result: Dict[str, Any]) -> None:
    """以结论优先的方式展示归因结果，技术细节由调用方单独折叠。"""
    summary = build_attribution_summary(result)
    current_period = summary["current_period"]
    comparison_period = summary["comparison_period"]
    scope = summary["scope"]
    direction = summary["direction"]
    delta = summary["total_delta"]
    change_rate = summary["change_rate"]

    st.markdown("### 经营结论")
    if change_rate is None:
        st.info("%s %s 销售额为 %s，较 %s 变化 %s。" % (
            scope, current_period, money(summary["current_total"]), comparison_period, money(delta)
        ))
    else:
        st.info("%s %s 销售额为 %s，较 %s%s %s，变化 %s。" % (
            scope,
            current_period,
            money(summary["current_total"]),
            comparison_period,
            direction,
            money(abs(delta)),
            percent(change_rate),
        ))

    cols = st.columns(4)
    cols[0].metric("本期销售额", money(summary["current_total"]))
    cols[1].metric("对比销售额", money(summary["comparison_total"]))
    cols[2].metric("变化金额", money(delta))
    cols[3].metric("变化比例", percent(change_rate))

    top_negative = summary["top_negative"]
    if not top_negative:
        st.success("当前没有可拆解的主要下降贡献因素。")
        return

    st.markdown("### 主要下降贡献")
    chart_rows = [
        {"因素": item.get("member", ""), "下降金额": abs(float(item.get("delta", 0)))}
        for item in top_negative[:5]
    ]
    st.bar_chart(chart_rows, x="因素", y="下降金额", horizontal=True, height=280)

    table = build_attribution_table(summary)
    st.dataframe([
        {
            "成员": item["成员"],
            "维度": item["维度"],
            "当前值": money(item["当前值"]),
            "对比值": money(item["对比值"]),
            "变化额": money(item["变化额"]),
            "下降贡献": percent(item["下降贡献"]),
        }
        for item in table
    ], width="stretch", hide_index=True)

    top_members = "、".join(item.get("member", "") for item in top_negative[:2])
    if summary["top_two_contribution"]:
        st.info("主要下降来自%s；前两项合计贡献 %s。" % (
            top_members, percent(summary["top_two_contribution"])
        ))

    st.markdown("### 建议核查")
    st.caption("以下是基于当前数据结构的核查线索，不是已验证的业务因果。")
    st.markdown(
        "- 核查下降门店的订单数、客流和客单价；\n"
        "- 核查下降门店的重点品类、库存和促销变化；\n"
        "- 核查渠道变化或数据采集异常。"
    )

    st.markdown("### 推荐继续追问")
    for question in build_follow_up_questions(summary):
        st.markdown("- %s" % question)


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
    llm_ready, model = openrouter_status()
    use_llm = cols[1].checkbox("使用 LLM（OpenRouter）", value=llm_ready, disabled=not llm_ready)
    if llm_ready:
        st.caption("OpenRouter 已配置（模型：%s）；模型只负责计划/文字，权限、SQL 和指标计算仍由本地逻辑负责。" % model)
    else:
        st.info("未配置 OPENROUTER_API_KEY，Agent 将使用确定性基线。请在 Render Environment 添加 Key 后重新部署。")
    run_btn = cols[2].button("执行 Agent", type="primary")
    user_id, role, data_scope = user_options[user_label]

    if run_btn:
        if "session_id" not in st.session_state:
            st.session_state["session_id"] = "st_" + uuid.uuid4().hex[:12]
        with st.status("Agent 执行中…", expanded=True) as status:
            status.write("解析意图 → 权限检查 → 执行 Skill → 校验结果 → 生成回答 → 审计")
            try:
                state = agent_service().query(
                    question, user_id=user_id, role=role, data_scope=data_scope,
                    use_llm=use_llm, session_id=st.session_state.get("session_id", "streamlit"),
                )
                st.session_state["agent_state"] = state
                status.update(label="Agent 执行完成", state="complete", expanded=False)
            except Exception as exc:  # noqa: BLE001
                with request_log_context(surface="agent_ui", use_llm=use_llm) as diagnostic:
                    log_event("agent_ui_request_failed", error_type=type(exc).__name__)
                status.update(label="Agent 执行失败", state="error", expanded=False)
                st.error("Agent 调用失败：%s\n诊断编号：%s" % (
                    type(exc).__name__, diagnostic.get("trace_id") or diagnostic.get("request_id", "N/A")
                ))

    state = st.session_state.get("agent_state")
    if state:
        intent = state.get("intent", "")
        perm = state.get("permission_decision", "")
        skill = state.get("current_skill", "")
        error_type = state.get("error_type")
        answer = state.get("answer", "")
        result = state.get("result") or {}

        if error_type:
            st.error(answer or "分析失败，请检查问题范围或稍后重试。")
            st.caption("诊断编号：%s" % (state.get("trace_id") or state.get("request_id") or "N/A"))
        elif answer:
            st.success("分析完成")

        # 业务结论优先；归因结果使用结构化展示，避免把多个因素挤在一段文字中。
        if intent == "attribution_analysis" and isinstance(result, dict) and result:
            _render_attribution_business_view(result)
        elif answer:
            st.markdown("### 结论")
            st.info(answer)

        # 执行过程默认折叠，作为分析依据保留。
        with st.expander("查看分析依据（技术详情）", expanded=False):
            st.markdown("#### 执行过程")
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

            llm_calls = state.get("llm_calls", [])
            if llm_calls:
                success_calls = [item for item in llm_calls if item.get("status") == "success"]
                fallback_calls = [item for item in llm_calls if item.get("status") == "fallback"]
                if success_calls:
                    st.success("OpenRouter 已调用 %d 次。" % len(success_calls))
                if fallback_calls:
                    st.warning("OpenRouter 未完成调用，已回退到确定性结果；不会影响权限和 SQL 安全校验。")

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

            for tr in state.get("tool_results", []):
                data = tr.get("data") or {}
                if isinstance(data, dict) and data.get("sql"):
                    st.code(data["sql"], language="sql")
                if isinstance(data, dict) and data.get("comparison_sql"):
                    st.code(data["comparison_sql"], language="sql")
            if result.get("metric_definition"):
                st.write("指标口径：", result["metric_definition"])

        # 结果数据
        if result and isinstance(result, dict) and result.get("rows"):
            st.markdown("### 结果数据")
            st.dataframe(result["rows"], width="stretch", hide_index=True)

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

    st.markdown("### 推荐问题")
    for item in examples:
        st.markdown("- %s" % item)


def render_quality() -> None:
    st.subheader("质量评测与审计")
    report = run_golden_v2(ROOT)
    results = report["results"]
    def pct(v):
        return "%.1f%%" % (v * 100) if v is not None else "-"
    cols = st.columns(4)
    cols[0].metric("总用例", "%d" % report["total"])
    cols[1].metric("通过率", pct(report["overall_pass_rate"]))
    cols[2].metric("Plan Accuracy", pct(report["plan_accuracy"]))
    cols[3].metric("Executable Success", "%s / %s" % (report["executable_cases"], report["total"]))
    cols = st.columns(4)
    cols[0].metric("Result Accuracy", pct(report.get("result_accuracy")))
    cols[1].metric("Permission Safety", pct(report.get("permission_safety_pass_rate")))
    cols[2].metric("Unsupported Reject", pct(report.get("unsupported_reject_rate")))
    cols[3].metric("Security Defense", pct(report.get("security_defense_rate")))
    st.caption("Executable Success Rate 只统计期望真正执行工具的用例；权限拒绝 / 不支持 / 安全拦截类用例不计入执行成功率分母。")
    st.markdown("### 分类型通过率")
    by_cat = report.get("by_category", {})
    st.dataframe([
        {"类型": cat, "用例数": info["total"], "通过": info["passed"], "通过率": pct(info.get("pass_rate"))}
        for cat, info in by_cat.items()
    ], width="stretch", hide_index=True)
    st.markdown("### Golden Dataset")
    st.dataframe([
        {"用例": item.get("case_id"), "问题": item.get("question"), "类型": item.get("category"),
         "结果": "PASS" if item.get("passed") else "FAIL",
         "执行": "Y" if item.get("executable") else "N",
         "返回行数": item.get("row_count", 0), "错误": "; ".join(item.get("errors") or [])}
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
