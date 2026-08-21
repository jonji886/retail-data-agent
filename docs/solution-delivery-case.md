# Solution / Delivery Case

本文用于说明一个面向零售经营分析的企业 AI 交付场景。以下为基于真实企业经营分析模式设计的模拟交付场景，不代表真实客户上线案例。

## 1. 客户背景

某全国零售连锁企业拥有总部、多个区域和数十家门店，经营人员主要依赖 BI Dashboard、Excel 和数据团队提供经营分析。总部希望让区域和门店负责人可以用自然语言追问经营变化，同时保留统一指标口径、权限边界和可验证证据。

## 2. As-Is：现状流程

```text
业务经理
↓
发现指标异常
↓
查看 BI Dashboard
↓
无法解释原因
↓
联系数据分析师
↓
确认指标口径
↓
数据分析师写 SQL
↓
Excel 分析
↓
发送分析结果
↓
业务继续追问
```

主要问题是：业务人员不能自然追问； ad-hoc 分析依赖数据团队；指标口径存在解释成本；总部、区域、门店权限不同；LLM 如果直接生成 SQL 会扩大安全风险；分析链路难审计；回答缺少可验证证据。

## 3. Business Pain Points

### 效率

简单经营问题也需要数据人员介入，业务等待时间长。

### 指标治理

同一指标在不同报表中可能有不同解释，复核成本高。

### 权限

总部、区域和门店角色的可见数据范围不同，不能把权限判断交给提示词。

### AI 风险

LLM 不能直接成为数据库执行权限主体，必须只生成受控的查询计划。

### 可验证性

每个回答都应能回答“为什么这么回答”：指标定义、权限范围、SQL、结果和 Trace 都应可追溯。

## 4. To-Be Solution

```text
Business User
       ↓
Natural Language Query
       ↓
AI Understanding
       ↓
Query Plan
       ↓
RBAC / Data Scope
       ↓
Semantic Layer
       ↓
Governed Skill
       ↓
ReadOnly SQL
       ↓
PostgreSQL
       ↓
Business Insight
       ↓
Evidence / Audit / Evaluation
```

设计原则是：**Probabilistic AI outside, deterministic execution inside.** DeepSeek 负责理解、结构化计划和自然语言表达；权限、指标公式、范围收窄、SQL 构造、执行和安全边界由确定性系统控制。OpenRouter 只作为可选故障切换，不改变执行边界。

## 5. 系统集成方案

### Identity

生产环境：

```text
Enterprise SSO / OIDC
        ↓
JWT
        ↓
User / Role / Data Scope
```

当前作品集为了 Demo 使用可切换 Identity，用来演示总部、区域和门店的数据范围差异；这不是生产 Authentication。

### Data

当前 Demo 使用 Supabase PostgreSQL，也保留 DuckDB 作为本地和 CI 的固定种子数据源。真实企业可以从 ERP、POS、CRM、Data Warehouse 或 Data Mart 经过 ReadOnly DB / API / Semantic Layer 接入 Agent。

### LLM

DeepSeek 仅承担 Intent understanding、Query Plan understanding、自然语言解释和推荐追问辅助生成。它不负责权限判断、任意 SQL 执行、指标公式定义或 Data Scope。

## 6. PoC 范围

PoC 做：

- KPI 查询、趋势分析、归因分析、异常分析和报告生成；
- RBAC、Semantic Layer、SQL Guard、Trace 和 Evaluation；
- 推荐追问点击后在当前会话中继续分析。

明确不做：

- 自动修改 ERP 数据、任意 SQL、Multi-Agent、长期 Memory；
- 自动业务决策或无人工控制的高风险 Action。

## 7. Acceptance Criteria

### Functional

- Golden Business Query 通过率 ≥ 95%；
- 支持 KPI / Trend / Attribution / Anomaly；
- 典型 Query 可正常执行。

### Security

- 越权访问拦截率 100%；
- 非 SELECT SQL 拦截率 100%；
- Unsupported request 有明确拒答。

### Data Governance

- 指标来自 Semantic Layer；
- 每次回答可追踪指标定义和 SQL。

### AI Quality

- 记录 Query Plan Accuracy、Executable Success、Result Accuracy 和 Unsupported Reject Accuracy；
- 评测报告记录主 Provider、实际 Provider 和 fallback。

### UX

- 业务用户无需查看 SQL 即可理解主要结论；
- 支持推荐追问连续分析；
- 技术证据默认折叠。

## 8. Productionization Checklist

当前 Portfolio MVP 尚未完成以下生产能力，不能把 Demo 身份切换或本地 JSONL 审计描述成生产就绪：

- Enterprise SSO / OIDC；
- Persistent Audit Store；
- Rate Limiting；
- Secret Management；
- HA 与 Disaster Recovery；
- Tenant Isolation；
- Enterprise Monitoring / Alerting；
- Full PII Governance；
- SLA / SLO。

## 9. Rollout Plan

### Phase 1：Discovery

确认用户角色、关键指标、数据源、权限和典型问题。

### Phase 2：PoC

准备 20～50 个 Golden Questions，先覆盖单一数据域、ReadOnly 和小范围用户。

### Phase 3：Pilot

邀请真实业务用户，收集 badcase，持续更新 Semantic Layer 和 Evaluation。

### Phase 4：Production

补齐 SSO、Persistent Audit、Monitoring、Security Review 和 SLA。

交付路径为：**Discovery → PoC → Evaluation → Pilot → Production**。
