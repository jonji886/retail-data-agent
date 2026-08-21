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
Streamlit UI ─┐
              ├→ AgentApplicationService → LangGraph Runtime
FastAPI API ──┘                                  ↓
                                      Query Plan / Policy / Skills
                                                   ↓
                                          Semantic Layer + SQL Guard
                                                   ↓
                              DataSourceBase → DuckDB / PostgreSQL

LLM：Application Service → OpenRouter Provider → Demo Router / 固定 Evaluation Model
横切：Trace / Audit / Metrics / Quota / Retry / Fallback / Evaluation
```

`DataSourceBase` 是业务访问边界。DuckDB 负责本地、CI 和 Deterministic Evaluation；
`PostgreSQLDataSource` 通过连接池、连接超时、statement timeout 和只读执行访问
Supabase。Skill、Semantic Layer 和 LangGraph 不判断底层数据库类型。

`AgentApplicationService` 是 Streamlit 与 FastAPI 的共同入口，负责调用 Agent、
Demo quota 和 Operational Metrics，避免 API 与前端产生两套业务逻辑。

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

SQL 安全边界是纵深防御，而不是只依赖一个正则：

```text
Query Plan
  ↓
Permission Guard
  ↓
Semantic Layer
  ↓
Application SQL Guard（SELECT-only / 单语句 / 禁止写操作与管理操作）
  ├→ DuckDB Capability Restriction（external access=false / 配置锁定）
  └→ PostgreSQL Read-only Adapter（statement_timeout / 连接池）
  ↓
Result Guard（max result rows / DuckDB memory+threads）
```

`ReadOnlySQLRunner` 校验只允许单条 `SELECT`，并拒绝
`INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/COPY/ATTACH/DETACH/PRAGMA/INSTALL/LOAD`。
但 SELECT 本身也可能调用 `read_csv`、`read_text`、`read_parquet` 或 HTTP table
function，因此每条只读连接都显式关闭 DuckDB `enable_external_access`，关闭扩展
自动安装/加载，并在配置完成后锁定。外部访问错误对用户只返回稳定的
`external_access_blocked`，不暴露本地路径或 DuckDB stacktrace。

默认资源策略为最多返回 1000 行、512MB memory limit、2 threads，可通过
`DB_MAX_RESULT_ROWS`、`DB_MEMORY_LIMIT`、`DB_THREADS` 做受控资源调整；没有可靠的
PostgreSQL 由连接参数提供 statement timeout；DuckDB 当前提供资源限制而不是伪装的
跨版本 hard timeout。

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
- LLM E2E：`scripts/run_llm_evaluation.py`（通过 OpenRouter，需 API Key + 固定 `EVAL_LLM_MODEL`，无则 skip）

OpenRouter 通过 OpenAI-compatible Chat Completions 接口调用。`OpenRouterNLQEngine.parse()`
在结构化输出异常时最多补请求一次，随后必须经过本地计划校验、相对时间策略、RBAC、
语义层和只读 SQL 执行器；Key 缺失、网络/API 异常或计划非法时回退到确定性基线。
回答润色同样只能使用已校验结果，不承担指标计算或权限判断。

### Relative Time Policy

`app/domain/time_range.py` 是 deterministic 与 LLM 两条解析链路共用的相对时间策略：
“过去/最近/近 N 个月”统一解释为包含当前月的 N 个自然月；“过去/最近/近 N 天”
解释为包含参考日的滚动 N 天。参考日来自数据集最新日期，不使用机器当前时间。

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

真实 LLM Badcase（`bc_llm_001`）：
- 问题：“过去3个月各区域销售额趋势”在真实报告中返回 24 行，Ground Truth 为 12 行；
- 根因：LLM 返回的相对日期未经过确定性策略归一化；
- 修复：统一时间策略覆盖相对时间的模型日期；
- 回归用例：g016，纳入 Golden Dataset；下一次真实 LLM 全量评测需复核。

## 9. Observability / Trace

每次 Agent Run 生成 `request_id` + `trace_id`，记录每个节点的：
- node / start_at / end_at / latency_ms / status / error

LLM 调用记录：provider / model / latency / retry_count / status / token usage / prompt_version（不记录 API Key）。

Tool 调用记录：tool_name / latency / status / error_type。

Operational Metrics 为进程内轻量指标，至少包含 request/success/failure、请求/LLM/Tool/DB
延迟、fallback、permission deny、unsupported、quota exceeded、provider、model 和 datasource。
公网 Demo quota 在 LLM 请求前检查 session/IP/global daily；Evaluation 直接调用 Agent，绕过 Demo quota。

## 10. API Boundary

```http
POST /api/v1/query
GET  /health
GET  /ready
```

`POST /api/v1/query` 接收 `user_id / question / use_llm / session_id`，返回 `run_id`、
status、intent、answer、permission decision、error type 和 latency。`/health` 只表示
进程存活；`/ready` 会检查语义配置与当前 DataSource。数据库不可用时 API 返回受控失败，
不暴露驱动异常或连接串。

## 11. 决策支持展示层（设计目标）

Agent 的确定性结果与面向老板的页面展示是两个不同边界：前者负责计算、校验和审计，后者负责信息排序、可视化和后续行动入口。展示层不得重新计算指标，也不得把贡献结果升级为未经验证的业务因果。

推荐的数据到页面流：

```text
Validated Result
  ↓
Business Summary（范围 / 期间 / KPI / 变化方向）
  ↓
Driver View（区域 / 门店 / 品类贡献表与图表）
  ↓
Evidence Status（事实 / 待核查线索 / 已验证因果）
  ↓
Next Questions（基于权限范围的后续追问）
  ↓
Evidence Drawer（Plan / Permission / SQL / Trace / Audit）
```

展示层的关键约束：

- 首屏优先展示业务结论，不要求用户理解 Intent、Skill 或 SQL；
- 贡献率标注为数据变化贡献，只有外部业务证据存在时才能陈述因果；
- 所有数字必须来源于已校验结果，并能追溯到指标口径和 SQL；
- 技术细节默认折叠，但权限拒绝、异常和失败状态必须显式可见；
- 下钻和后续追问继续沿用 RBAC + Data Scope，不得因可视化扩大权限。

当前 Streamlit MVP 已实现第一版展示层：结论、KPI、贡献表与横向柱状图、核查建议以及默认折叠的依据区。展示模型位于 `app/presentation/decision_support.py`，不重新计算指标；贡献因素点击下钻、追问按钮自动执行和跨图表联动仍未实现。产品验收要求与示例见 `docs/decision-support-ui.md`。

## 12. 未来扩展

- DataSource Adapter（MySQL / Warehouse）
- Durable Checkpointer（Redis / PostgreSQL）
- Human-in-the-loop（加入写操作 Tool 时）
- 统计/时序模型预警
- 多轮上下文
- Render Free Demo 部署（当前路径见 `docs/deploy-render.md`）
- 生产级公网部署与监控
