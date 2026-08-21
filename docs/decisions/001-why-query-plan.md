# ADR 001：为什么保留 Query Plan

## Context

用户问题包含指标、维度、过滤范围、时间和对比关系。直接让模型生成 SQL，会把这些业务含义、权限边界和数据库语法混在一次不可控输出里。

## Problem

系统需要在执行前检查指标是否注册、过滤值是否允许、时间窗口是否有效，并让 Golden Dataset 能独立断言模型理解结果。

## Options

1. 直接 Text-to-SQL；2. 规则解析后直接拼 SQL；3. 先生成受限的结构化 Query Plan，再由确定性语义层生成 SQL。

## Decision

选择第三种。LLM 或确定性解析器只产生 `intent / metric / dimensions / filters / time_range / comparison`，计划经过白名单、权限和语义层校验后才能执行。

## Trade-offs

多了一层契约和校验代码，复杂问题需要扩展计划字段；但安全边界、评测粒度和错误定位明显更清晰。

## Consequences

业务 SQL 不暴露给模型自由生成，计划可以被审计、回放和加入回归集；无法可靠映射的问题会拒答，而不是猜测。
