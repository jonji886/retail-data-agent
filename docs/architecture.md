# 架构说明

## 1. 为什么使用 LangGraph

项目存在明确的状态传递、条件路由、统一生命周期、错误路径、权限检查和 Skill 编排需求。
如果用纯函数串行调用，错误路径与权限拒绝需要大量嵌套 if/else，状态在函数间传递不透明，难以审计与测试。

LangGraph 提供：

- **StateGraph**：以 `AgentState` 为中心，节点显式声明输入输出，状态流转可追踪。
- **Conditional Edge**：条件路由（unsupported / denied / error / success）以声明式表达，替代散落的 if/else。
- **统一生命周期**：每次 Agent Run 都经过 parse → policy → skill → validate → answer → audit，失败路径不绕过审计。

不使用 LangGraph 的 Agent / Tool calling 等高级抽象，仅用 StateGraph 作为轻量 Runtime，保持可控与可测试。

## 2. 为什么不让 LLM 直接调用数据库

直接让 LLM 生成并执行 SQL 会带来：

- **安全性**：无法阻止非法 SQL（DROP/DELETE/注入）。
- **口径一致性**：同一指标在不同问题中可能生成不同 SQL，口径漂移。
- **可审计**：LLM 生成的 SQL 难以人工复核，错误难以定位。
- **可测试**：无法用固定评测集回归。

本项目采用：

```
LLM → Query Plan（结构化意图）
      → Schema Validation（Pydantic / 白名单）
      → Business Validation（指标/维度/过滤值/时间）
      → Permission Check（RBAC + Data Scope）
      → Semantic Layer（MetricCatalog 生成 SQL）
      → Read-only Tool（ReadOnlySQLRunner 校验并执行）
      → Result Validation
      → Answer Generation（基于已验证事实）
```

LLM 只参与"理解"与"表达"，不参与"执行"与"安全"。

## 3. 为什么不是 Multi-Agent

当前业务没有多个高度自治角色协作的必要。
采用：

```
1 Orchestrator（LangGraph Runtime）
  + Multiple Skills（确定性业务能力）
  + Deterministic Tools（原子执行能力）
```

更简单、更稳定、更容易评测。
Multi-Agent 引入的协调成本、非确定性和评测难度，对本项目的 ROI 为负。

## 4. 分层架构

```
┌─────────────────────────────────────────┐
│           Agent Layer (LangGraph)       │
│  parse_request → policy_check →         │
│  execute_skill → validate_result →      │
│  generate_answer → audit_run            │
├─────────────────────────────────────────┤
│           Skill Layer                   │
│  metric_query / trend_analysis /        │
│  anomaly_analysis / attribution /       │
│  report_generation                      │
├─────────────────────────────────────────┤
│           Tool Layer                    │
│  MetricQueryTool / PermissionChecker /  │
│  EntityResolver / MetadataTool /        │
│  ReadOnlySQLRunner                      │
├─────────────────────────────────────────┤
│      Data / Semantic Layer              │
│  MetricCatalog (metrics.json) /         │
│  DuckDB / ReadOnlySQLRunner             │
└─────────────────────────────────────────┘
```

### LLM 边界

| 步骤 | 是否使用 LLM | 说明 |
|------|-------------|------|
| parse_request（意图+计划） | 可选 | LLM 生成结构化 Query Plan，离线可回退到确定性规则 |
| policy_check | 否 | 纯程序 RBAC + Data Scope |
| execute_skill | 否 | 确定性 Python 业务逻辑 |
| validate_result | 否 | 确定性数值/结构校验 |
| generate_answer | 可选 | LLM 基于已验证事实生成总结，离线用模板 |
| audit_run | 否 | 纯程序记录 |

## 5. Agent Flow

```
START
  ↓
parse_request
  ↓ (conditional)
  ├─ unsupported → unsupported_response → audit → END
  └─ policy_check
       ↓ (conditional)
       ├─ deny → permission_denied → audit → END
       └─ execute_skill
            ↓ (conditional)
            ├─ error → error_response → audit → END
            └─ validate_result
                 ↓ (conditional)
                 ├─ error → error_response → audit → END
                 └─ generate_answer → audit → END
```

## 6. Security 设计

### RBAC + Data Scope

权限顺序：LLM Plan → Policy Check → Authorized Query Plan → Semantic Layer → SQL。

- **禁止**：查询全部数据再过滤。
- **禁止**：依赖 Prompt 遵守权限。

| 角色 | scope | 规则 |
|------|-------|------|
| hq_manager | all | 不收窄，允许任意 filters |
| region_manager | region | 必须查询本人区域；越权 → DENY；未指定 → 注入本人区域 |
| store_manager | store | 必须查询本人门店；越权 → DENY；未指定 → 注入本人门店 |

### ReadOnly SQL

`ReadOnlySQLRunner` 校验：
- 只允许 SELECT
- 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/COPY 等
- 只允许单条语句
- DuckDB 以 `read_only=True` 打开

## 7. Evaluation 设计

### Golden Dataset

35 个用例，覆盖：
- normal（单指标/多维/同比/环比/TopN/过滤）
- expression（同义词表达变化）
- trend（多期趋势）
- attribution / anomaly / report
- boundary（无数据/不支持指标/空结果）
- security（DROP/DELETE/Prompt 注入）
- permission（HQ/Region/Store 越权）

### 指标

指标口径以 `docs/evaluation.md` 为准：

- Plan Accuracy
- Executable Success Rate（denominator = 期望执行业务工具的 27 个用例，不含拒绝/拦截类）
- Result Accuracy（ground truth 数值校验）
- Unsupported Reject Rate
- Permission Safety Pass Rate
- Security Defense Rate
- Overall Pass Rate

### 两条链路

- Deterministic Baseline：`scripts/run_evaluation.py`（无 API Key 可运行）
- LLM E2E：`scripts/run_llm_evaluation.py`（需 API Key，无则 skip）

## 8. Badcase 生命周期

```
发现 → 分类 → Root Cause → Fix → Regression Case → Resolved
```

字段：badcase_id / event_id / question / category / reason / expected / actual /
root_cause / fix / fixed_version / regression_case_id / status / created_at / resolved_at。

Demo Badcase（`bc_demo_001`）：
- 问题："各区域营业额"
- 原因：sales_amount synonyms 未包含"营业额"
- 修复：metrics.json 添加同义词
- 回归用例：g009（PASS）

## 9. Observability / Trace

每次 Agent Run 生成 `request_id` + `trace_id`，记录每个节点的：
- node / start_at / end_at / latency_ms / status / error

LLM 调用记录：provider / model / latency / status / prompt_version（不记录 API Key）。

Tool 调用记录：tool_name / latency / status / error_type。

## 10. 未来扩展

- DataSource Adapter（PostgreSQL / MySQL / Warehouse）
- Durable Checkpointer（Redis / PostgreSQL）
- Human-in-the-loop（加入写操作 Tool 时）
- 统计/时序模型预警
- 多轮上下文
- 公网部署与监控
