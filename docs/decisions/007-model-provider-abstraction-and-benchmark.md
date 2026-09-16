# ADR 007：Model Provider 抽象与可重复 Benchmark

> 状态：Accepted（2026-09-16）

## Context

项目原先通过 OpenAI-compatible 接口连接 SiliconFlow，并已有 LangGraph Agent、模型角色、确定性回退、真实 LLM E2E 与 Golden Dataset。新增模型时不应让 Agent 节点、Skill 或治理逻辑依赖 Provider，也不应为每个模型复制一条评测链路。

## Decision

- 以 `ProviderSpec` 注册 Provider 的 API Key 环境变量、Base URL、展示名称和默认模型；由 `LLM_PROVIDER` 选择 DeepSeek API、Qwen/阿里云百炼或 SiliconFlow。
- 复用同一 OpenAI-compatible 客户端和现有 Router / Main / Reason / Vision 角色，不增加专用 SDK；Provider-scoped `*_API_KEY`、`*_BASE_URL`、`*_MAIN_MODEL` 等变量允许多个 Provider 同时配置。
- Agent 业务图、Prompt、Tool、语义层、权限和 SQL 执行不因 Provider 切换而变化；所有模型输出继续经过本地校验。
- 单模型 LLM E2E 沿用现有 Golden 判定；`scripts/run_model_benchmark.py` 在同一 PostgreSQL 数据源上逐 Provider、逐 Case 执行，并记录物理调用（含重试）、延迟、Provider 或估算 Token、价格表成本、错误与 fallback。
- 集中维护价格；Cost 是非账单估算，不对不同币种做隐式换汇。没有可靠输出 Token 的失败调用不虚构 Cost。

## Consequences

可以仅通过环境变量切换 Provider，也能在固定 Golden Dataset 上复核模型选型；对比结果仍受 API 波动、模型非确定性与实际部署环境影响，Markdown 报告会标明数据集版本、运行次数、币种和估算范围。缺少凭证的 Provider 显示为 SKIP，不会被当作零成本或零错误。

既有 `SiliconFlowClient` / `SiliconFlowConfig` 名称保留为兼容别名；新 Agent / 脚本入口使用 provider-neutral 工厂。
