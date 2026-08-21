# ADR 006：为什么采用 Provider 抽象并固定 Evaluation 模型

## Context

OpenRouter 提供 OpenAI-compatible 网关和多模型选择，适合 Portfolio Demo；但 `openrouter/free` 背后的模型会动态变化，不适合做可比较的评测基线。

## Problem

如果业务代码散落具体模型字符串，Provider、模型、重试和降级会互相耦合，出现故障时也难以判断是网关还是模型问题。

## Options

1. 直接在各处写模型 slug；2. 只使用免费 Router；3. 由 `OpenRouterProvider` 承载模型配置，Demo 与 Evaluation 使用不同策略。

## Decision

选择第三种并补充跨 Provider 故障切换。`LLM_MODEL` 控制 Demo，允许 `openrouter/free`；
`EVAL_LLM_MODEL` 必须是具体固定模型。OpenRouter 是主 Provider，客户端统一处理 timeout、
有限重试、usage 记录；配置 `DEEPSEEK_API_KEY` 后，OpenRouter 仍失败时对同一请求最多
切换一次 DeepSeek（默认 `deepseek-chat`），两个 Provider 都失败才使用确定性 fallback。

## Trade-offs

固定模型可能更贵或不可用，需要手动更新；DeepSeek fallback 会增加一次 Provider 成本和
延迟，也可能造成不同模型的输出差异。但评测报告可以按 provider、model、retry、
`fallback_used` 和最终 deterministic fallback 分层分析，避免把故障切换伪装成主模型准确率。

## Consequences

OpenRouter / DeepSeek API Key 只从环境变量读取，审计不记录凭证；Provider 切换不会绕过
权限、语义层或只读 SQL 边界。生产场景应同时配置两者并监控 `fallback_rate`；没有
`DEEPSEEK_API_KEY` 时仍保持原有确定性 fallback 行为。
