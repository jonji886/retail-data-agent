"""自然语言相对时间的统一解析策略。

策略固定但参考日期可注入：
- ``过去/最近/近 N 个月``：包含参考日期所在的自然月，共 N 个自然月；
- ``本月``：当月 1 日至参考日；``上个月``：上一个完整自然月；
- ``今年``：本年 1 月 1 日至参考日；``去年``：上一完整自然年；
- ``过去/最近 N 天``：包含参考日在内的滚动 N 个日历日。

生产数据源以数据集最新日期作为 reference_date，避免依赖机器当前时间。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass(frozen=True)
class RelativeTimeRange:
    start_date: date
    end_date: date
    grain: str
    label: str


_COUNT_RE = r"(?:\d+|[一二两三四五六七八九十]+)"
_MONTH_RE = re.compile(r"(?:过去|最近|近)\s*(%s)\s*个?月" % _COUNT_RE)
_DAY_RE = re.compile(r"(?:过去|最近|近)\s*(%s)\s*天" % _COUNT_RE)
_CHINESE_DIGITS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def resolve_relative_time(question: str, reference_date: date) -> Optional[RelativeTimeRange]:
    """将问题中的相对时间表达归一化；没有相对时间时返回 ``None``。"""
    if match := _MONTH_RE.search(question):
        count = _parse_count(match.group(1))
        if count < 1 or count > 24:
            raise ValueError("目前支持查询过去 1～24 个月")
        start_month = _shift_month(reference_date.replace(day=1), -(count - 1))
        return RelativeTimeRange(
            start_date=start_month,
            end_date=reference_date,
            grain="month",
            label="过去%d个月" % count,
        )

    if match := _DAY_RE.search(question):
        count = _parse_count(match.group(1))
        if count < 1 or count > 366:
            raise ValueError("目前支持查询过去 1～366 天")
        return RelativeTimeRange(
            start_date=reference_date - timedelta(days=count - 1),
            end_date=reference_date,
            grain="day",
            label="过去%d天" % count,
        )

    if "本季度" in question or "当前季度" in question:
        quarter_start_month = ((reference_date.month - 1) // 3) * 3 + 1
        return RelativeTimeRange(
            start_date=date(reference_date.year, quarter_start_month, 1),
            end_date=reference_date,
            grain="month",
            label="本季度",
        )
    if "今年" in question or "本年度" in question:
        return RelativeTimeRange(
            start_date=date(reference_date.year, 1, 1),
            end_date=reference_date,
            grain="month",
            label="今年",
        )
    if "去年" in question or "上年度" in question:
        return RelativeTimeRange(
            start_date=date(reference_date.year - 1, 1, 1),
            end_date=date(reference_date.year - 1, 12, 31),
            grain="month",
            label="去年",
        )
    if "上月" in question or "上个月" in question:
        previous = _shift_month(reference_date.replace(day=1), -1)
        return RelativeTimeRange(
            start_date=previous,
            end_date=_last_day(previous.year, previous.month),
            grain="month",
            label="上月",
        )
    if "本月" in question or "当前月" in question:
        return RelativeTimeRange(
            start_date=reference_date.replace(day=1),
            end_date=reference_date,
            grain="month",
            label="本月",
        )
    return None


def _parse_count(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if raw == "十":
        return 10
    if len(raw) == 2 and raw[0] == "十":
        return 10 + _CHINESE_DIGITS[raw[1]]
    if len(raw) == 2 and raw[1] == "十":
        return _CHINESE_DIGITS[raw[0]] * 10
    if len(raw) == 3 and raw[1] == "十":
        return _CHINESE_DIGITS[raw[0]] * 10 + _CHINESE_DIGITS[raw[2]]
    if len(raw) == 1 and raw in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[raw]
    raise ValueError("无法识别相对时间数量：%s" % raw)


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(index, 12)
    return date(year, month_index + 1, 1)


def _last_day(year: int, month: int) -> date:
    next_month = _shift_month(date(year, month, 1), 1)
    return next_month - timedelta(days=1)
