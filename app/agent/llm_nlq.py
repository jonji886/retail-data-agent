"""使用 OpenRouter 解析自然语言，再交给确定性语义层执行。"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Mapping

from app.agent.nlq import DateRange, NLQError, NaturalLanguageQueryEngine, ParsedQuestion
from app.data_sources.base import DataSourceBase
from app.domain.time_range import resolve_relative_time
from app.llm.openrouter_client import OpenRouterClient, OpenRouterConfig


class LLMPlanError(NLQError):
    """大模型计划格式或内容不符合语义层约束。"""


class OpenRouterNLQEngine:
    def __init__(self, root: Path, data_source: DataSourceBase | None = None) -> None:
        self.root = root
        self.deterministic = NaturalLanguageQueryEngine(root, data_source=data_source)
        self.config = OpenRouterConfig.from_env(root)
        self.client = OpenRouterClient(self.config)

    def parse(self, question: str) -> ParsedQuestion:
        """调用 OpenRouter 生成计划，再通过本地规则完成严格校验。"""
        plan_json = self.client.complete_json(self._system_prompt(), question)
        try:
            plan = self._parse_json(plan_json)
        except LLMPlanError:
            # 结构化输出异常只允许一次补请求；之后由 Agent 回退到确定性解析。
            if self.config.max_retries <= 0:
                raise
            plan = self._parse_json(self.client.complete_json(self._system_prompt(), question))
        return self._build_parsed_question(question, plan)

    def answer(self, question: str):
        parsed = self.parse(question)
        return self.deterministic.answer_parsed(parsed, question)

    def _system_prompt(self) -> str:
        metrics = []
        for name in self.deterministic.catalog.names():
            metric = self.deterministic.catalog.get(name)
            metrics.append({
                "name": metric.name,
                "display_name": metric.display_name,
                "synonyms": metric.synonyms,
                "dimensions": metric.dimensions,
                "time_grains": metric.time_grains,
            })
        return (
            "你是零售经营分析 Data Agent 的查询计划解析器。\n"
            "你的任务是把用户的中文问题转换成结构化 JSON。\n"
            "禁止生成 SQL，禁止编造数据，禁止输出 JSON 之外的内容。\n"
            "数据最新日期是 2025-12-31；没有明确时间时使用本月（2025-12）。\n"
            "相对时间必须按统一规则理解：过去/最近/近 N 个月包含当前月，共 N 个自然月；"
            "过去/最近/近 N 天为包含当前日的滚动 N 天。\n"
            "同比 comparison=yoy，环比 comparison=mom，否则 comparison=null。\n"
            "所有 metric、dimension、filter key 必须使用下面提供的规范名称。\n\n"
            "输出格式：\n"
            "{\"metric\":\"sales_amount\",\"dimensions\":[],\"filters\":{},"
            "\"time_grain\":\"month\",\"start_date\":\"2025-12-01\","
            "\"end_date\":\"2025-12-31\",\"comparison\":null,\"clarification\":null}\n\n"
            "指标目录：\n%s\n\n"
            "可用维度和值：\n%s"
            % (
                json.dumps(metrics, ensure_ascii=False),
                json.dumps(self.deterministic.dimension_config, ensure_ascii=False),
            )
        )

    @staticmethod
    def _parse_json(content: str) -> Mapping[str, Any]:
        clean = content.strip()
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise LLMPlanError("模型没有返回合法 JSON：%s" % exc) from exc
        if not isinstance(payload, dict):
            raise LLMPlanError("模型计划必须是 JSON 对象")
        return payload

    def _build_parsed_question(self, question: str, plan: Mapping[str, Any]) -> ParsedQuestion:
        clarification = plan.get("clarification")
        if clarification:
            raise LLMPlanError("需要澄清：%s" % clarification)
        metric_name = plan.get("metric")
        if not isinstance(metric_name, str) or metric_name not in self.deterministic.catalog.names():
            raise LLMPlanError("模型返回了未注册指标：%s" % metric_name)
        metric = self.deterministic.catalog.get(metric_name)
        dimensions = plan.get("dimensions", [])
        filters = plan.get("filters", {})
        if not isinstance(dimensions, list) or not all(isinstance(item, str) for item in dimensions):
            raise LLMPlanError("dimensions 必须是字符串数组")
        if not isinstance(filters, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in filters.items()):
            raise LLMPlanError("filters 必须是字符串键值对象")
        unsupported_dimensions = [item for item in dimensions if item not in metric.dimensions]
        unsupported_filters = [item for item in filters if item not in metric.dimensions]
        if unsupported_dimensions or unsupported_filters:
            raise LLMPlanError("指标不支持指定的维度或过滤条件")
        allowed_values = self._allowed_filter_values()
        for key, value in filters.items():
            if value not in allowed_values.get(key, set()):
                raise LLMPlanError("过滤值不在语义层允许范围内：%s=%s" % (key, value))

        time_grain = plan.get("time_grain", "month")
        if not isinstance(time_grain, str) or time_grain not in metric.time_grains:
            raise LLMPlanError("指标不支持时间粒度：%s" % time_grain)
        try:
            relative = resolve_relative_time(question, self.deterministic.reference_date)
        except ValueError as exc:
            raise LLMPlanError(str(exc)) from exc
        if relative:
            # LLM 可以识别意图，但不能自行决定相对时间窗口；统一由确定性策略收敛。
            start_date = relative.start_date
            end_date = relative.end_date
            date_label = relative.label
            time_grain = relative.grain
            if time_grain not in metric.time_grains:
                raise LLMPlanError("指标不支持相对时间粒度：%s" % time_grain)
        else:
            start_date = self._date(plan.get("start_date"), "start_date")
            end_date = self._date(plan.get("end_date"), "end_date")
            date_label = "%s 至 %s" % (start_date, end_date)
        if start_date > end_date:
            raise LLMPlanError("时间范围无效")
        comparison = plan.get("comparison")
        if comparison not in (None, "yoy", "mom"):
            raise LLMPlanError("comparison 只能是 yoy、mom 或 null")
        return ParsedQuestion(
            question=question.strip(),
            metric=metric,
            dimensions=dimensions,
            filters=filters,
            date_range=DateRange(start_date, end_date, time_grain, date_label),
            comparison=comparison,
        )

    def _allowed_filter_values(self) -> Dict[str, set]:
        values: Dict[str, set] = {}
        for name, config in self.deterministic.dimension_config.items():
            raw_values = config.get("values", [])  # type: ignore[union-attr]
            values[name] = set(raw_values)
        return values

    @staticmethod
    def _date(value: Any, field: str) -> date:
        if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            raise LLMPlanError("%s 必须是 YYYY-MM-DD" % field)
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise LLMPlanError("%s 不是有效日期" % field) from exc
