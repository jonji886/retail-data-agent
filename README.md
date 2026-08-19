# Retail Data Agent — 企业经营分析 Agent MVP

> 将自然语言经营问题，转换为**受治理、可审计、可评测**的数据分析执行流程的 Agent MVP。
> 面向 FDE / Agent 交付岗位的作品集项目：不追求框架数量，追求**架构边界、权限安全、评测验证与交付一致性**。

```
Status: MVP
Version: v0.6.0
Last verified: 2026-08-19

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
| SQL safety | 只读 SQL 执行器，禁止写操作与多语句 |
| Observability | Trace（逐节点事件）+ Audit（JSONL 审计日志） |
| Quality | Golden Dataset（35 用例，9 类场景，见 `docs/evaluation.md`） |
| Regression | 自动化评测（Deterministic + LLM 两种模式） |

所有能力均有对应代码、测试或报告证据，无超前宣传。

---

## Evaluation（当前结果）

> 数据来自 `reports/evaluation_report.json`（确定性评测，Evaluation 2.0）。指标口径与分母定义见 [docs/evaluation.md](docs/evaluation.md)。

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

LLM 增强评测（真实调用 DeepSeek，记录 model / llm_calls / fallback）：`python3 scripts/run_llm_evaluation.py`。未配置 `DEEPSEEK_API_KEY` 时不生成 LLM 报告，避免"0 calls / 100% pass"的误导性结果。

---

## 5-Minute Demo

1. 启动 Web Demo（见下方 Quick Start），打开 **Agent** Tab；
2. 提问：**"为什么华东区域 11 月销售额下降了？"**；
3. 展示归因回答（哪个门店 / 品类贡献了主要下降）；
4. 展开执行链路：Query Plan → Skill → SQL → Trace；
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

# 2.（可选）配置 LLM：复制 .env.example 为 .env 并填写 DEEPSEEK_API_KEY
cp .env.example .env

# 3. 启动 Web Demo
streamlit run app/web_app.py
```

### 常用命令

```bash
# 单元测试（14 个测试文件，72 个用例）
python3 -m unittest discover -s tests

# 确定性评测（生成 reports/evaluation_report.json）
python3 scripts/run_evaluation.py

# LLM 增强评测（需要 DEEPSEEK_API_KEY）
python3 scripts/run_llm_evaluation.py

# 项目一致性校验（README / 配置 / 报告 / Web Tabs）
python3 scripts/verify_project_consistency.py

# 语义层与只读查询 Smoke Test
python3 scripts/smoke_query.py

# Docker 部署
docker compose up --build
```

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
  web_app.py    # Streamlit Web Demo（6 个 Tab）
configs/
  metrics/      # 指标口径（语义层单一来源）
  evaluation/   # Golden Dataset（35 用例）
  users.json    # RBAC 角色与数据权限
scripts/        # 评测、一致性校验、Smoke Test、Ground Truth 生成
reports/        # evaluation_report.json / llm_evaluation_report.json
tests/          # 14 个测试文件，72 个用例
docs/           # architecture / evaluation / demo-script
```

---

## 能力边界

本项目定位 **Enterprise-oriented MVP**，明确不做：

- PostgreSQL / MySQL 等外部数据库（当前使用本地 DuckDB 虚拟数据）；
- Multi-Agent、MCP、RAG、Vector DB、Kubernetes、微服务；
- 复杂监控平台与可观测产品。

这些是"下一阶段候选"，不是"已实现能力"。见 [SPEC.md](SPEC.md) 的 Non-goals 与 Future。

---

## 文档索引

- [SPEC.md](SPEC.md)：MVP Product Specification（问题、范围、验收标准）
- [docs/architecture.md](docs/architecture.md)：架构与设计决策
- [docs/evaluation.md](docs/evaluation.md)：评测目标、Golden Dataset、指标口径
- [docs/demo-script.md](docs/demo-script.md)：面试演示脚本（5～10 分钟）
- [docs/README_GUIDELINES.md](docs/README_GUIDELINES.md)：README 编写规范
