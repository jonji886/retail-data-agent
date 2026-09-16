# ADR 006：为什么采用硅基流动网关与模型优先级

> 状态：历史决策（2026-08-24）。Provider 选择已由 [ADR 007](007-model-provider-abstraction-and-benchmark.md) 扩展为可配置；本文的 Router / Main / Reason / Vision 职责边界仍有效。

## Context

项目需要一个 OpenAI-compatible 中转站统一承载模型调用，同时保留模型不可用、限流或超时时的可恢复能力。当前硅基流动账户按 Router、Main、Reason、Vision 四个角色配置模型。

## Problem

如果业务代码散落具体模型字符串，Provider、模型、重试和降级会互相耦合；如果直接使用动态路由，故障时也难以判断实际使用了哪个模型，评测结果无法复核。

## Decision

由 `SiliconFlowClient` 统一读取 `SILICONFLOW_BASE_URL`、`SILICONFLOW_API_KEY` 和 `ROUTER`、`MAIN`、`REASON`、`VISION` 四个变量。Router 只用于低成本意图提示；Main 是默认文本模型，按 `LLM_MAX_RETRIES` 有限重试仍失败后才调用 Reason；Vision 只由未来多模态入口显式选择。

Demo 默认使用 `MAIN`，Router/Reason/Vision 按调用角色选择。Evaluation 可用 `EVAL_LLM_MODEL` 固定 Main 评测模型；每次调用都记录 provider、role、实际 model、重试和 fallback 元数据，但不记录凭证。

## Trade-offs

同一网关内的模型切换增加了少量延迟和成本，也可能带来输出风格差异；作为交换，角色职责清晰，Main 的文本能力与 Reason 的恢复能力可以独立调整，Vision 不会意外进入文本 fallback。

## Consequences

所有模型生成的查询计划都必须经过本地计划校验、相对时间策略、RBAC、语义层和只读 SQL 执行器。模型优先级只影响理解/表达，不改变权限、安全或指标口径边界。没有 `SILICONFLOW_API_KEY` 时，系统继续使用确定性链路。
