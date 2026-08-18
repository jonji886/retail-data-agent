"""权限检查 Tool：基于 RBAC + Data Scope 的确定性程序控制。

权限顺序：LLM Plan → Policy Check → Authorized Query Plan → Semantic Layer → SQL。
禁止"查询全部数据再过滤"，也禁止依赖 Prompt 遵守权限。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from app.agent.contracts import ErrorType, ToolResult


class PermissionError(Exception):
    """越权或权限不足。"""


class PermissionChecker:
    """根据用户角色与数据范围，对 Query Plan 中的 filters 做最小权限收窄。

    规则：
    - hq_manager (scope=all): 不收窄，允许任意 filters。
    - region_manager (scope=region): 必须且只能查询本人区域；
      若 plan 指定了其它区域 → deny；若未指定 → 注入本人区域。
    - store_manager (scope=store): 必须且只能查询本人门店；
      若 plan 指定了其它门店/区域/城市 → deny；若未指定 → 注入本人门店。
    """

    def __init__(self, root: Path) -> None:
        self.users_path = root / "configs" / "users.json"

    def load_users(self) -> Dict[str, Any]:
        return json.loads(self.users_path.read_text(encoding="utf-8"))

    def get_user(self, user_id: str) -> Dict[str, Any]:
        users = self.load_users().get("users", {})
        if user_id not in users:
            raise PermissionError("未知用户：%s" % user_id)
        return users[user_id]

    def check_and_authorize(
        self,
        user_id: str,
        plan_filters: Mapping[str, str],
    ) -> Tuple[bool, Dict[str, str], Optional[str]]:
        """返回 (allow, authorized_filters, deny_reason)。

        authorized_filters 是经过权限收窄后的安全 filters，可直接交给语义层。
        """
        user = self.get_user(user_id)
        scope = user.get("data_scope", {})
        scope_type = scope.get("scope", "all")
        filters = dict(plan_filters)

        if scope_type == "all":
            return True, filters, None

        if scope_type == "region":
            allowed_region = scope.get("region_name")
            requested_region = filters.get("region_name")
            if requested_region and requested_region != allowed_region:
                return False, filters, "区域经理无权查询其它区域：%s" % requested_region
            # 若用户请求了 store_id / city_name 但未指定 region，也需注入 region 约束
            filters["region_name"] = allowed_region
            return True, filters, None

        if scope_type == "store":
            allowed_store_id = scope.get("store_id")
            allowed_store_name = scope.get("store_name")
            allowed_region = scope.get("region_name")
            requested_store = filters.get("store_id") or filters.get("store_name")
            if requested_store and requested_store not in (allowed_store_id, allowed_store_name):
                return False, filters, "门店经理无权查询其它门店：%s" % requested_store
            # 门店经理不允许查询其它区域/城市
            requested_region = filters.get("region_name")
            if requested_region and allowed_region and requested_region != allowed_region:
                return False, filters, "门店经理无权查询其它区域：%s" % requested_region
            requested_city = filters.get("city_name")
            if requested_city and requested_city != scope.get("city_name"):
                return False, filters, "门店经理无权查询其它城市：%s" % requested_city
            # 门店经理不允许跨区域/城市查询（即使不指定门店也只看本门店）
            filters["store_id"] = allowed_store_id
            # 清除可能造成越权的 region/city（以 store_id 为准）
            filters.pop("region_name", None)
            filters.pop("city_name", None)
            return True, filters, None

        return False, filters, "未知权限范围：%s" % scope_type

    def check(self, user_id: str, plan_filters: Mapping[str, str]) -> ToolResult:
        """ToolResult 包装版本，便于审计与统一错误处理。"""
        try:
            allow, authorized, reason = self.check_and_authorize(user_id, plan_filters)
        except PermissionError as exc:
            return ToolResult(
                success=False,
                error_type=ErrorType.UNAUTHORIZED_SCOPE,
                error_message=str(exc),
                metadata={"user_id": user_id},
            )
        if not allow:
            return ToolResult(
                success=False,
                error_type=ErrorType.UNAUTHORIZED_SCOPE,
                error_message=reason or "越权",
                metadata={"user_id": user_id, "requested_filters": dict(plan_filters)},
            )
        return ToolResult(
            success=True,
            data={"authorized_filters": authorized},
            metadata={"user_id": user_id, "scope": self.get_user(user_id).get("data_scope", {})},
        )
