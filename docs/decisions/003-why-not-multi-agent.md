# ADR 003：为什么不引入 Multi-Agent

## Context

当前产品是固定的经营分析流程：解析计划、做权限判断、调用确定性 Skill、校验结果并回答。不同步骤有明确输入输出，不需要自治角色协商。

## Problem

引入多个 Agent 会增加状态同步、协调、超时和评测组合数量，也会让权限责任更难解释。

## Options

1. 多 Agent 自主协作；2. 一个 LangGraph Orchestrator 编排多个确定性 Skill；3. 全部写成无边界脚本。

## Decision

选择第二种。LangGraph 负责可命名的生命周期和分支，业务能力放在 Skill，SQL 和权限放在确定性 Tool。

## Trade-offs

牺牲了展示“Agent 数量”的技术噱头，但减少了协调开销和非确定性；未来只有在出现独立自治角色、不同工具权限和独立目标时才重新评估。

## Consequences

面试演示可以沿 `trace_id` 解释每个节点的责任，CI 也能对每个业务分支做可重复回归。
