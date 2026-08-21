# Retail Data Agent — MVP Product Specification

```
Status: MVP
Version: v0.6.0
Last verified: 2026-08-20
```

> 本文件描述当前已实现的 MVP 产品范围与验收标准，与 README / 代码 / 评测报告保持一致。
> 已实现能力标记 `Implemented`；未实现能力只出现在 Non-goals 或 Future，不再以"P2 计划中"形式混在需求中。

## 1. Problem

企业经营分析团队日常面对大量"查询-核对-归因-报告"类重复工作。传统 BI 依赖固定报表与人工写 SQL，存在三个问题：

1. **口径不一致**：同一指标在不同报表中定义不同；
2. **权限难收敛**：直接写 SQL 难以保证"能看到的数据 = 被授权看到的数据"；
3. **不可审计**：谁问了什么、看到什么、SQL 是什么，缺少记录。

## 2. Users

| 用户 | 角色 | 数据权限 | 典型诉求 |
| ---- | ---- | -------- | -------- |
| 总部经理 | hq_manager | 全部区域 | 全局分析、归因、报告 |
| 区域经理 | region_manager | 所属区域 | 区域内指标、趋势 |
| 门店经理 | store_manager | 所属门店 | 本店指标、防越权访问 |

## 3. Use Cases（当前 MVP 覆盖）

- 指标查询：销售额 / 毛利率 / 订单数 等单指标或多指标查询（含同比环比）；
- 趋势分析：指定时间段内指标变化趋势；
- 归因分析：某区域 / 某指标下降或增长的原因拆解；
- 异常检测：指定月份内的销售异常预警；
- 报告生成：生成指定区域 / 月份的经营分析报告；
- 权限边界：不同角色访问其权限范围内数据，越权访问被拒绝；
- 不支持请求：无法识别或超出能力范围的问题被明确拒答。

## 4. Scope（Implemented）

### 4.1 Agent Runtime（LangGraph）

- 有状态编排图：`parse_request → policy_check → execute_skill → validate_result → generate_answer`，含 unsupported / denied / error 分支。
- 查询计划（Query Plan）：intent / metric / dimensions / filters / time range / comparison 的结构化中间产物。
- 双链路解析：确定性基线（NLQ Engine）+ LLM 增强（DeepSeek，需 API Key），LLM 不可用时自动回退且记录 fallback。

### 4.2 语义层与工具

- 指标口径单一来源：`configs/metrics/metrics.json`。
- 只读 SQL 执行器：仅允许 SELECT，拒绝写操作 / 多语句 / 非白名单表。
- Skill 分层：metric_query / attribution / anomaly / report，按意图路由。

### 4.3 权限与安全

- RBAC：`configs/users.json` 定义角色与用户。
- Data Scope：按 role 注入数据范围（region / store），查询计划层注入过滤条件。
- 越权访问返回 DENY，且不执行任何业务工具。
- Prompt Injection / 不支持请求被识别为 unsupported 并拒答。
- DuckDB 只读连接关闭 external access、扩展自动加载/安装并锁定配置；结果最多返回 1000 行，默认 memory limit 512MB、2 threads。
- SQL guard 拒绝外部文件、HTTP table function、extension install/load 等绕过路径，并返回稳定 reason code。

### 4.4 可观测与审计

- Trace：每个节点的事件记录（node / status / latency）。
- Audit：JSONL 审计日志（question / user / intent / plan / tool_calls / result / status）。
- Badcase 记录：Web Demo 支持标记失败案例。

### 4.5 评测

- Golden Dataset：`configs/evaluation/golden_questions.json`，35 个用例，覆盖 9 类场景（normal / expression / trend / attribution / anomaly / report / boundary / permission / security）。
- Evaluation 2.0：分层指标（Plan Accuracy、Executable Success Rate、Result Accuracy、Unsupported Reject Rate、Permission Safety Pass Rate、Security Defense Rate、Overall Pass Rate）。
- LLM E2E 评测：真实调用 LLM，记录 model / llm_calls / fallback，未配置 Key 时明确 SKIP 且不生成报告。
- 相对时间策略：`过去/最近/近 N 个月`、自然月和滚动天数由 `app/domain/time_range.py` 统一解析，LLM 计划不能覆盖该规则。

### 4.7 CI 质量门禁

- GitHub Actions 在 Push / Pull Request 上执行 ruff、compileall、完整单测、确定性 Golden 评测、一致性检查和 smoke test；任一步失败都会阻断。
- 真实 LLM Evaluation 只通过手动 workflow 运行，API Key 仅来自 GitHub Secret，不进入普通 PR CI。

### 4.6 Web Demo（Streamlit）

- 6 个 Tab：经营总览 / Agent / 自然语言问数 / 预警与归因 / 智能报告 / 质量评测。
- 支持切换用户身份（权限）、LLM 开关、审计记录查看。

### 4.7 数据

- 本地 DuckDB 虚拟零售数据（固定种子，可复现），覆盖 2024～2025 年。

## 5. Non-goals（当前 MVP 明确不做）

- 外部数据库（PostgreSQL / MySQL / ClickHouse 等适配）；
- Multi-Agent、MCP、RAG、Vector DB；
- 流式处理（Kafka）与分布式编排（Kubernetes）；
- 前端重构（React 等）；
- 复杂监控平台；
- 预测、库存、供应链等新增业务 Agent。

## 6. Security Requirements（Implemented）

- [x] SQL 只读执行，写操作被拒绝；
- [x] RBAC 角色与 Data Scope 数据权限注入；
- [x] 越权请求在计划层拦截，不发生工具执行；
- [x] 不支持 / 注入类请求明确拒答；
- [x] 审计日志记录完整执行链路；
- [x] 敏感配置（API Key）只通过环境变量注入，不提交仓库。
- [x] DuckDB external access、扩展自动安装/加载被关闭，配置在连接内锁定。
- [x] SQL 结果行数、memory limit 与 threads 有明确默认上限。

## 7. Evaluation Requirements

- 确定性评测必须全量可跑：`python3 scripts/run_evaluation.py`；
- 执行成功率分母 = 期望执行业务工具的用例（权限拒绝 / 不支持 / 安全拦截不计入）；
- LLM 评测必须区分运行模式，禁止输出"0 LLM calls / 100% pass"的误导报告；
- 一致性校验：`python3 scripts/verify_project_consistency.py` 必须通过。
- CI 阻断门禁必须覆盖静态检查、单测、确定性评测、一致性检查和 smoke test；真实 LLM 评测单独手动运行。

## 8. Acceptance Criteria

1. `README == 当前实际实现`，状态块数字与配置 / 报告一致；
2. `Golden Dataset 数量（35）== README 描述 == 评测报告 total`；
3. `Web Demo Tab 数量（6）== README 描述 == web_app.py 实际`；
4. `Overall Pass Rate` 与 `Executable Success Rate` 口径可解释、不冲突；
5. 全部单元测试通过（当前 16 文件 / 85 用例）；
6. 任何指标或能力声明都能在代码 / 测试 / 报告中找到证据。

## 9. Future（Out of Scope，未实现不宣传）

- 外部数据库适配与生产级数据源；
- 多 Agent 协作与工具生态（MCP 等）；
- 真实 LLM 在线评测自动进入每次 PR；
- 更细粒度的审计可视化。
