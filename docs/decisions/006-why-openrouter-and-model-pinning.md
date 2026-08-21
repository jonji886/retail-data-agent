# ADR 006：为什么采用 Provider 抽象并固定 Evaluation 模型

## Context

OpenRouter 提供 OpenAI-compatible 网关和多模型选择，适合 Portfolio Demo；但 `openrouter/free` 背后的模型会动态变化，不适合做可比较的评测基线。

## Problem

如果业务代码散落具体模型字符串，Provider、模型、重试和降级会互相耦合，出现故障时也难以判断是网关还是模型问题。

## Options

1. 直接在各处写模型 slug；2. 只使用免费 Router；3. 由 `OpenRouterProvider` 承载模型配置，Demo 与 Evaluation 使用不同策略。

## Decision

选择第三种。`LLM_MODEL` 控制 Demo，允许 `openrouter/free`；`EVAL_LLM_MODEL` 必须是具体固定模型。客户端统一处理 timeout、有限重试、usage 记录和确定性 fallback。

## Trade-offs

固定模型可能更贵或不可用，需要手动更新；但评测报告可复现，故障可以按 provider、model、retry 和 fallback 分层分析。

## Consequences

API Key 只从环境变量读取，审计不记录凭证；模型失败不会绕过权限、语义层或只读 SQL 边界。
