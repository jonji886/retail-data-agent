# ADR 004：为什么分离 Deterministic 与 Real LLM Evaluation

## Context

确定性链路验证权限、语义层、SQL 安全和结果计算；真实 LLM 链路验证自然语言理解，但会受到模型版本、网络、免费额度和服务波动影响。

## Problem

若两类结果混为一个百分比，CI 无法稳定阻断回归，也容易把没有真实调用的“100%”误解成模型准确率。

## Options

1. 所有测试都调用免费 Router；2. 只测确定性链路；3. 离线回归与固定模型 E2E 分开报告。

## Decision

选择第三种。普通 CI 运行 DuckDB + Deterministic Regression；手动 E2E 必须配置 `EVAL_LLM_MODEL` 的具体模型，报告记录 provider、model、调用数、fallback、延迟和 token。

## Trade-offs

真实评测成本和运行时间更高，且不能每次 PR 阻断；但结果可比较，失败 Case 可以单独定位并沉淀为回归用例。

## Consequences

Demo 可以使用 `openrouter/free`，Evaluation 禁止使用动态免费 Router，README 不再把两类指标包装成一个数字。
