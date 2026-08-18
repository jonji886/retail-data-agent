"""Agent 契约：Intent 枚举、Query Plan、ToolResult、错误分类。

这些类型是 Agent 层与 Skill / Tool 层之间的稳定接口。
- Intent: 受控白名单，LLM 输出必须命中其一，否则视为 unsupported。
- QueryPlan: 统一查询计划，兼容现有 ParsedQuestion。
- ToolResult: Tool 的统一返回结构。
- ErrorType: 统一错误分类，便于审计与评测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Mapping, Optional


# ---------------------------------------------------------------------------
# Intent 白名单
# ---------------------------------------------------------------------------

class Intent:
    """受控意图枚举。LLM 必须返回其中之一，不允许任意字符串直接执行。"""
    METRIC_QUERY = "metric_query"
    TREND_ANALYSIS = "trend_analysis"
    ANOMALY_ANALYSIS = "anomaly_analysis"
    ATTRIBUTION_ANALYSIS = "attribution_analysis"
    REPORT_GENERATION = "report_generation"
    METRIC_EXPLANATION = "metric_explanation"
    UNSUPPORTED = "unsupported"

    ALL = (
        METRIC_QUERY,
        TREND_ANALYSIS,
        ANOMALY_ANALYSIS,
        ATTRIBUTION_ANALYSIS,
        REPORT_GENERATION,
        METRIC_EXPLANATION,
        UNSUPPORTED,
    )

    # 可执行的 Skill intent（不含 UNSUPPORTED）
    SKILLABLE = (
        METRIC_QUERY,
        TREND_ANALYSIS,
        ANOMALY_ANALYSIS,
        ATTRIBUTION_ANALYSIS,
        REPORT_GENERATION,
    )


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------

class ErrorType:
    """统一错误分类，审计保留技术类型，前端展示友好信息。"""
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    INVALID_PLAN = "INVALID_PLAN"
    INVALID_METRIC = "INVALID_METRIC"
    INVALID_DIMENSION = "INVALID_DIMENSION"
    INVALID_FILTER = "INVALID_FILTER"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    UNAUTHORIZED_SCOPE = "UNAUTHORIZED_SCOPE"
    EMPTY_RESULT = "EMPTY_RESULT"
    QUERY_ERROR = "QUERY_ERROR"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_INVALID_OUTPUT = "LLM_INVALID_OUTPUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    RESULT_VALIDATION_ERROR = "RESULT_VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Query Plan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QueryPlan:
    """统一查询计划。

    兼容现有 ParsedQuestion，同时支持 attribution / report 等多 intent。
    对不需要的字段允许使用默认值。
    """
    intent: str
    metric: str
    dimensions: List[str] = field(default_factory=list)
    filters: Mapping[str, str] = field(default_factory=dict)
    time_grain: str = "month"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    comparison: Optional[str] = None  # yoy / mom / None
    # 归因专用
    attribution_dimension: Optional[str] = None
    # 报告专用
    report_month: Optional[str] = None
    report_region: Optional[str] = None
    # 元信息
    clarification: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "metric": self.metric,
            "dimensions": list(self.dimensions),
            "filters": dict(self.filters),
            "time_grain": self.time_grain,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "comparison": self.comparison,
            "attribution_dimension": self.attribution_dimension,
            "report_month": self.report_month,
            "report_region": self.report_region,
            "clarification": self.clarification,
        }


# ---------------------------------------------------------------------------
# Tool Result
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    """Tool 的统一返回结构，便于校验与审计。"""
    success: bool
    data: Any = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }
