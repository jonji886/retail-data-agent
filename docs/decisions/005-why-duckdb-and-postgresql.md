# ADR 005：为什么同时支持 DuckDB 与 PostgreSQL

## Context

DuckDB 适合本地开发、CI 和固定种子评测；Supabase 提供托管 PostgreSQL，更接近企业应用的数据访问环境。两者的角色不同，不应互相替代。

## Problem

如果业务逻辑直接依赖某个数据库驱动，切换 Demo、CI 和托管数据库会带来重构，也会让 Skill 感知基础设施细节。

## Options

1. 只保留 DuckDB；2. 将 Supabase 作为业务专用实现；3. 定义 `DataSourceBase`，以 DuckDB 和 PostgreSQL 适配器实现。

## Decision

选择第三种。Supabase 按标准 PostgreSQL 使用，命名为 `PostgreSQLDataSource`；DataSource 工厂从 `DATA_SOURCE`、`DATABASE_URL` 和数据库资源参数初始化。

## Trade-offs

需要处理参数占位符、日期格式和连接池差异，且 PostgreSQL 初始化需要脚本；换来的是本地可复现性与生产近似环境并存。

## Consequences

语义层、RBAC、Skill 和 LangGraph 不判断具体数据库。两种数据源必须用同一个 Hero Scenario 做结果一致性验收。
