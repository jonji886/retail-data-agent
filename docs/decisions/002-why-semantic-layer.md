# ADR 002：为什么使用 Semantic Layer

## Context

销售额、订单数、毛利等指标有固定业务口径，查询会从不同入口进入 Agent。若每个 Skill 自己实现公式，口径会随着功能增长而漂移。

## Problem

需要让指标定义、允许维度、时间粒度和来源表有单一事实来源，同时保留 SQL 执行前的安全检查。

## Options

1. 在 Prompt 中描述指标；2. 每个 Skill 内硬编码公式；3. 以版本化配置驱动目录，由目录生成受控聚合 SQL。

## Decision

选择第三种。`configs/metrics/metrics.json` 是指标目录，`MetricCatalog` 负责解析、校验并生成 SQL；Skill 只提交计划，不重复实现指标公式。

## Trade-offs

新指标需要更新配置和测试，不能即时接受任意字段；换来的好处是指标口径可审查、跨数据源复用并可做确定性评测。

## Consequences

DuckDB 与 PostgreSQL 共享业务语义，底层数据源只负责执行；语义配置错误会在启动或查询校验阶段暴露，而不是静默产生错误数字。
