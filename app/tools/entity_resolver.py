"""实体解析 Tool：把用户表达解析为 canonical name / entity id。

低基数维度（region/channel/category/brand/city）继续走配置化；
高基数维度（store）通过数据库查询解析，避免把数千实体塞入 Prompt。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import duckdb

from app.agent.contracts import ToolResult


class EntityResolver:
    """将用户的自然表达解析为维度规范值。

    MVP 阶段主要处理 store_name / store_id 的模糊匹配，
    其它低基数维度仍由 dimensions.json 的 aliases 覆盖。
    """

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def resolve_store(self, text: str) -> Optional[Dict[str, str]]:
        """根据文本模糊匹配门店，返回 {store_id, store_name, region_name, city_name}。"""
        if not text:
            return None
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            # 先精确匹配 store_name，再尝试 store_id，最后模糊 like
            rows: List[tuple] = connection.execute(
                """
                SELECT store_id, store_name, region_name, city_name
                FROM dim_store
                WHERE store_name = ? OR store_id = ? OR store_name LIKE ?
                ORDER BY
                    CASE WHEN store_name = ? THEN 0
                         WHEN store_id = ? THEN 1
                         ELSE 2 END
                LIMIT 1
                """,
                [text, text, "%" + text + "%", text, text],
            ).fetchall()
        finally:
            connection.close()
        if not rows:
            return None
        store_id, store_name, region_name, city_name = rows[0]
        return {
            "store_id": str(store_id),
            "store_name": str(store_name),
            "region_name": str(region_name),
            "city_name": str(city_name),
        }

    def resolve(self, dimension: str, text: str) -> ToolResult:
        """统一入口。"""
        if dimension == "store_name" or dimension == "store_id":
            result = self.resolve_store(text)
            if result:
                return ToolResult(success=True, data=result, metadata={"dimension": dimension, "input": text})
            return ToolResult(
                success=False,
                error_type="ENTITY_NOT_FOUND",
                error_message="未找到匹配的门店：%s" % text,
                metadata={"dimension": dimension, "input": text},
            )
        # 低基数维度由上层配置处理，这里不重复实现
        return ToolResult(
            success=False,
            error_type="UNSUPPORTED_DIMENSION",
            error_message="EntityResolver 暂不支持维度：%s" % dimension,
            metadata={"dimension": dimension},
        )
