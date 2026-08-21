# Retail Data Agent — 企业经营分析 Agent MVP

[![CI](https://github.com/jonji886/retail-data-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/jonji886/retail-data-agent/actions/workflows/ci.yml)

> 将自然语言经营问题，转换为**受治理、可审计、可评测**的数据分析执行流程的 Agent MVP。
> 面向 FDE / Agent 交付岗位的作品集项目：不追求框架数量，追求**架构边界、权限安全、评测验证与交付一致性**。

```
Status: MVP
Version: v0.6.0
Last verified: 2026-08-21

Golden cases: 35
Evaluation cases: 35
Demo scenarios: 4
Web tabs: 6
```

> 上表为项目状态单一事实来源，由 `python3 scripts/verify_project_consistency.py` 自动校验，防止文档与代码漂移。

> 以下为真实运行截图（非 AI 生成 UI 图）。生成方式：启动 Web Demo 后运行
> `python3 scripts/capture_demo_shots.py`（需 playwright），
> 输出到 `docs/assets/`。

![Agent 主界面](docs/assets/agent-demo.png)
![Trace / 执行链路](docs/assets/agent-trace.png)
![质量评测](docs/assets/evaluation.png)

---

## 一句话定位

**Retail Data Agent** 是一个面向企业经营分析场景的 Agent MVP：用户用自然语言提问（如"华东区域 11 月销售额为什么下降"），系统将其解析为结构化 Query Plan，经过 **权限校验 → 归因 Skill → 语义层 → 只读 SQL 执行 → 结果校验** 后返回业务回答，全程记录 Trace 与 Audit。

核心设计理念：

> **LLM 只负责"理解与表达"，不直接承担权限判断、业务口径和 SQL 执行等确定性职责。**
> `LLM does not directly execute business-critical operations.`

---

## Hero Scenario：华东区域 11 月销售额为什么下降？

这是项目的主演示场景（对应 Golden Case `g018`，Web Demo Agent Tab 默认问题）。

```text
业务问题
   ↓
意图识别 / Query Plan（intent=attribution_analysis）
   ↓
RBAC / Data Scope 权限校验（allow）
   ↓
Attribution Skill（按 store / city / category 拆分贡献）
   ↓
Semantic Layer（统一指标口径，生成受控 SQL）
   ↓
只读 SQL Tool（只允许 SELECT，禁止写操作）
   ↓
结果校验（非空、口径核对）
   ↓
业务归因回答（哪个门店/品类拖累最大）
   ↓
Trace / Audit（记录 intent、plan、权限、SQL、结果）
```

该场景可一键在 Web Demo 中复现，详见 [docs/demo-script.md](docs/demo-script.md)。

### 老板视角的输出目标

当前 Agent 已能给出可审计的销售变化贡献结果，但老板真正关心的是“发生了什么、为什么发生、接下来做什么”。面向经营管理者的页面目标是：

- 先展示范围、期间、核心指标、变化金额和变化比例；
- 用表格或图表展示主要区域 / 门店 / 品类的下降贡献；
- 明确区分已验证数据事实、待核查线索和未经验证的业务因果；
- 将 Intent、Skill、Permission、SQL、Trace 等技术细节放入可展开的分析依据区；
- 提供可继续追问的经营问题和核查建议。

当前 MVP 已实现第一版决策支持视图：结论、KPI、主要下降贡献图表、核查建议和折叠的技术依据。贡献因素点击下钻和自动执行后续追问仍未实现，完整要求与差距记录在 [docs/decision-support-ui.md](docs/decision-support-ui.md)。

---

## 核心架构

```text
User（角色 + 数据权限）
  ↓
Agent Runtime（LangGraph，有状态编排）
  ↓
Query Plan（intent / metric / filters / 时间范围）
  ↓
Policy（RBAC + Data Scope 校验）
  ↓
Skill（归因 / 异常 / 报告 / 指标查询）
  ↓
Semantic Layer（指标口径单一来源）
  ↓
Governed Tool（只读 SQL 执行器）
  ↓
Data Source（本地 DuckDB，虚拟零售数据）
```

旁挂三条可观测 / 质量链路：**Trace、Audit、Evaluation**。

详细设计见 [docs/architecture.md](docs/architecture.md)。

---

## 三项关键设计决策

### 1. 为什么用 LangGraph（有状态编排图）

需要明确的节点边界（解析 / 权限 / 执行 / 校验 / 回答）、可测试的状态流转，以及为 Trace 与评测提供结构化的中间产物。使用 LangGraph 是因为它把 Agent 流程变成**可命名、可路由、可测试**的图，而不是把框架本身当作卖点。

### 2. 为什么不做直连 Text-to-SQL

```text
Natural Language → Query Plan → Semantic Layer → Controlled SQL
```

而不是直接 `LLM → SQL`。这样保证：

- **指标一致性**：所有口径来自 `configs/metrics/metrics.json` 语义层，不随 Prompt 漂移；
- **权限可控**：SQL 必须经过 RBAC / Data Scope 注入过滤，越权问题在计划层面拦截；
- **可预测、可测试**：Query Plan 是中间产物，Golden Dataset 可以独立评测"计划正确性"。

### 3. 为什么不用 Multi-Agent

当前场景是一个受约束的数据分析执行流程，不存在多个高度自治角色协作的刚性需求。因此选择：

```text
single orchestrated graph（单一编排图）
```

而不是 `multiple autonomous agents`。原因：

- 更容易评测（状态图每个节点可断言）；
- 更少非确定性（不依赖多 Agent 协商）；
- 更低协调成本，更适合企业交付与回归。

---

## Engineering Evidence

| Enterprise Concern | Implementation |
| ------------------ | -------------- |
| Agent orchestration | LangGraph StateGraph |
| Business semantics | Semantic Layer（`configs/metrics/metrics.json` 为单一口径来源） |
| Tool governance | Skill + Tool 分层调用，按意图路由 |
| Permission | RBAC（角色/用户）+ Data Scope（区域/门店数据权限） |
| SQL safety | 应用层 SQL Guard + DuckDB external access lockdown + 只读连接 + 结果行数限制 |
| Observability | Trace（逐节点事件）+ Audit（JSONL 审计日志） |
| Quality | Golden Dataset（35 用例，9 类场景，见 `docs/evaluation.md`） |
| Regression | 自动化评测（Deterministic + LLM 两种模式） |

所有能力均有对应代码、测试或报告证据，无超前宣传。

---

## Evaluation（两条证据链分开）

> `Deterministic Regression ≠ Real LLM Accuracy`。前者验证编排、权限、语义层和执行链路的可重复回归；后者使用真实模型评测自然语言理解，受模型、网络和 quota 影响，不能混合统计。指标口径与分母定义见 [docs/evaluation.md](docs/evaluation.md)。

### Deterministic Regression

> 来源：`reports/evaluation_report.json`；命令：`python3 scripts/run_evaluation.py`。该报告是普通 PR 的 CI merge gate。

| Metric | Value |
| ------ | ----- |
| Golden Dataset | 35 cases（normal / expression / trend / attribution / anomaly / report / boundary / permission / security） |
| Overall Pass Rate | 100%（35/35） |
| Plan Accuracy | 100% |
| Executable Success Rate | 100%（27/27，仅统计期望执行业务工具的用例） |
| Result Accuracy | 100% |
| Unsupported Reject Rate | 100% |
| Permission Safety Pass Rate | 100% |
| Security Defense Rate | 100% |

### Real LLM E2E Evaluation

> 来源：`reports/llm_evaluation_report.json`，最近一次真实运行时间 `2026-08-19`，模型 `deepseek-v4-flash`。命令：`python3 scripts/run_llm_evaluation.py`；需配置 `DEEPSEEK_API_KEY`，也可手动触发 [GitHub Actions workflow](https://github.com/jonji886/retail-data-agent/actions/workflows/llm-evaluation.yml)。

| Metric | Last verified value |
| ------ | ------------------- |
| Cases | 35 |
| Passed / Overall Pass Rate | 34/35（97.1%） |
| Executable Success | 26/27（96.3%） |
| LLM Calls | 51 |
| Fallback Count / Rate | 2 / 5.7% |
| Total Duration | 198.7s |

当前环境未配置 API Key，因此本轮没有伪造新的真实 LLM 数字；上表保留最近一次真实报告。相对时间 Badcase 已完成代码修复，待下一次完整真实评测复核。

### Known / Resolved Badcases

| Badcase | Root cause | Fix / regression |
| -------- | ---------- | ---------------- |
| `bc_demo_001`：各区域营业额 | `sales_amount` 同义词缺少“营业额” | 更新语义层；`g009` 回归通过 |
| `bc_llm_001`：过去3个月各区域销售额趋势 | LLM 日期未经过统一相对时间策略，报告出现 24 行而 Ground Truth 为 12 行 | 新增 relative-time policy，`g016` 纳入 Golden；真实 LLM 报告待复跑 |

### CI Quality Gate

每次 Push / Pull Request 自动执行以下阻断门禁；任一步骤失败都会使 CI 失败：

```text
Prepare DuckDB fixture
  → ruff check .
  → compileall
  → unit tests
  → deterministic Golden evaluation
  → project consistency check
  → smoke test
```

真实 LLM Evaluation 不进入普通 PR CI，只能通过手动 workflow 运行，API Key 仅来自 GitHub Secret。

---

## 5-Minute Demo

1. 启动 Web Demo（见下方 Quick Start），打开 **Agent** Tab；
2. 提问：**"为什么华东区域 11 月销售额下降了？"**；
3. 先展示业务结论（变化金额、变化比例和主要下降贡献），再说明当前 Demo 的技术执行链路；
4. 展开执行链路：Query Plan → Skill → SQL → Trace，并说明这些是分析依据而不是老板主结论；
5. 切换为"门店经理 (user_store_01)"，提问华东区域数据，展示 **DENY**（权限边界）；
6. 打开 **质量评测** Tab，展示 35 用例、分类型通过率与安全指标。

完整话术与节奏见 [docs/demo-script.md](docs/demo-script.md)（4 个场景，5～10 分钟）。

---

## Quick Start

### 环境要求

- Python 3.10+
- 依赖见 `requirements.txt`

### 安装与启动

```bash
# 1. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 生成本地可复现数据（首次运行或数据文件不存在时）
python3 scripts/generate_data.py
python3 scripts/init_db.py

# 3.（可选）配置 LLM：复制 .env.example 为 .env 并填写 DEEPSEEK_API_KEY
cp .env.example .env

# 4. 启动 Web Demo
streamlit run app/web_app.py
```

### 常用命令

```bash
# 单元测试（17 个测试文件，93 个用例）
python3 -m unittest discover -s tests

# 确定性评测（生成 reports/evaluation_report.json）
python3 scripts/run_evaluation.py

# LLM 增强评测（需要 DEEPSEEK_API_KEY）
python3 scripts/run_llm_evaluation.py

# 项目一致性校验（README / 配置 / 报告 / Web Tabs）
python3 scripts/verify_project_consistency.py

# 语义层与只读查询 Smoke Test
python3 scripts/smoke_query.py

# 与 GitHub Actions 相同的本地质量门禁（真实 LLM 不在其中）
ruff check .
python3 -m compileall app

# Docker 部署
docker compose up --build
```

## Render Free 部署

当前 MVP 可以使用 Render Free Web Service 运行，不需要 Supabase。部署使用仓库内的 `Dockerfile` 和 `render.yaml`，应用启动时会生成固定种子的本地 DuckDB 数据。

最小配置如下：

```text
Runtime: Docker
Instance Type: Free
PORT: 8501
Health Check Path: /_stcore/health
```

详细控制台配置、环境变量、验证步骤和免费版数据持久化限制见 [docs/deploy-render.md](docs/deploy-render.md)。Render Free 适合 Demo 和低流量验证；审计日志与 DuckDB 文件不保证跨重启持久化。

### 项目结构

```text
app/
  agent/        # LangGraph Runtime：parse → policy → skill → validate → answer
  llm/          # LLM 客户端（DeepSeek），prompt 纳入版本控制
  quality/      # Evaluation 2.0 + Audit 审计
  skills/       # 归因 / 异常 / 报告 / 指标查询 Skill
  tools/        # 语义层、只读 SQL 执行、权限、元数据
  analytics/    # 归因与异常分析算法
  reporting/    # 周报生成
  presentation/ # 面向经营管理者的结果展示模型
  web_app.py    # Streamlit Web Demo（6 个 Tab）
configs/
  metrics/      # 指标口径（语义层单一来源）
  evaluation/   # Golden Dataset（35 用例）
  users.json    # RBAC 角色与数据权限
scripts/        # 评测、一致性校验、Smoke Test、Ground Truth 生成
reports/        # evaluation_report.json / llm_evaluation_report.json
tests/          # 17 个测试文件，93 个用例
docs/           # architecture / evaluation / demo-script / deploy-render
```

---

## 能力边界

本项目定位 **Enterprise-oriented MVP**，明确不做：

- PostgreSQL / MySQL 等外部数据库（当前使用本地 DuckDB 虚拟数据）；
- Multi-Agent、MCP、RAG、Vector DB、Kubernetes、微服务；
- 复杂监控平台与可观测产品；
- 生产级公网部署、高可用和持久化审计（当前仅提供 Render Free Demo 部署路径）。

当前归因结果表示数据变化贡献，不自动证明促销、库存、客流或其他业务因果；管理者仍需结合业务事实复核。老板视角的页面信息层级、图表和行动建议要求见 [docs/decision-support-ui.md](docs/decision-support-ui.md)。

这些是"下一阶段候选"，不是"已实现能力"。见 [SPEC.md](SPEC.md) 的 Non-goals 与 Future。

---

## 文档索引

- [SPEC.md](SPEC.md)：MVP Product Specification（问题、范围、验收标准）
- [docs/architecture.md](docs/architecture.md)：架构与设计决策
- [docs/evaluation.md](docs/evaluation.md)：评测目标、Golden Dataset、指标口径
- [docs/demo-script.md](docs/demo-script.md)：面试演示脚本（5～10 分钟）
- [docs/decision-support-ui.md](docs/decision-support-ui.md)：老板视角的经营决策视图设计目标
- [docs/deploy-render.md](docs/deploy-render.md)：Render Free 部署说明与限制
- [docs/README_GUIDELINES.md](docs/README_GUIDELINES.md)：README 编写规范
