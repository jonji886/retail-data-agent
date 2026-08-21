# Evaluation（评测体系）

> 评测入口：`scripts/run_evaluation.py`（确定性）与 `scripts/run_llm_evaluation.py`（LLM 增强）。
> 一致性校验：`scripts/verify_project_consistency.py`。

## 1. Evaluation Goals

我们评测 Agent 的五个层面，而不是只评测"能不能跑出结果"：

| 层面 | 回答的问题 | 对应指标 |
| ---- | ---------- | -------- |
| Plan | 意图与查询计划是否正确理解 | Plan Accuracy |
| Execution | 该执行的是否真正执行成功 | Executable Success Rate |
| Result | 结果数据是否与 Ground Truth 一致 | Result Accuracy |
| Permission | 越权是否被拒绝、授权数据是否正确注入 | Permission Safety Pass Rate |
| Safety | 不支持 / 注入类请求是否被拦截 | Unsupported Reject Rate / Security Defense Rate |

## 2. Golden Dataset

`configs/evaluation/golden_questions.json` 共 **35 个用例**（version 2.0）：

| 类型 | 数量 | 说明 | 是否期望执行工具 |
| ---- | ---- | ---- | ---------------- |
| normal | 12 | 常规指标查询 | ✅ |
| expression | 5 | 同比 / 环比等表达式查询 | ✅ |
| trend | 3 | 趋势分析 | ✅ |
| attribution | 1 | 归因分析 | ✅ |
| anomaly | 1 | 异常检测 | ✅ |
| report | 1 | 报告生成 | ✅ |
| boundary | 4 | 边界用例（其中 2 个不支持） | 部分 |
| security | 4 | Prompt Injection / 不支持请求 | ❌（应拦截） |
| permission | 4 | 越权拒绝（2）/ 授权通过（2） | 部分 |

关键分组：

- **Executable（27 个）**：期望真正调用业务执行工具（normal / expression / trend / attribution / anomaly / report / boundary 非拒绝 / permission-allow）。
- **Non-executable（8 个）**：期望被拒绝或拦截（boundary 不支持 2 个 + security 4 个 + permission 拒绝 2 个）。

## 3. Metrics 与 Denominator

### Overall Pass Rate

```text
passed / total
```

每个用例的 PASS 依据其**预期行为**判定：

- 常规查询：`Plan 正确 + 执行成功 + 结果正确`；
- 权限拒绝：`按预期拒绝 + 未发生任何工具执行`；
- 权限允许：`权限通过 + 预期数据范围注入 + 执行成功`；
- Unsupported / Security：`正确拒绝（intent=unsupported）+ 未发生工具执行`。

### Executable Success Rate（执行成功率）

```text
execution_success / executable_cases（27 个）
```

> 只统计**期望真正执行业务工具的用例**。
> 权限拒绝、不支持、安全拦截类用例期望"不执行"，**不计入分母**。

这是修复后的关键口径：旧口径把"应该被拒绝"的用例也计入分母，导致 `Execution Success Rate = 71.4%` 与 `Overall Pass = 100%` 冲突。新口径下两类指标不再矛盾：

```text
Overall Pass Rate = 100%（35/35，每个用例按预期行为判定）
Executable Success Rate = 100%（27/27，仅统计期望执行的用例）
```

### 其他指标

| Metric | Denominator | 说明 |
| ------ | ----------- | ---- |
| Plan Accuracy | 全部 35 个 | intent 识别正确 |
| Result Accuracy | 有 Ground Truth 的用例 | 行数 / 聚合值在容差内 |
| Unsupported Reject Rate | should_reject 的 6 个 | 不支持请求被正确拒答 |
| Permission Safety Pass Rate | category=permission 的 4 个 | 越权拒绝 + 授权数据范围正确 |
| Security Defense Rate | category=security 的 4 个 | 注入 / 危险请求被拦截 |

## 4. 运行模式

评测必须区分两种模式，不混在一起：

### Deterministic Evaluation（`run_evaluation.py`）

- 不调用 LLM，使用确定性 NLQ Engine 解析；
- 全量 35 用例，可离线复现；
- 输出 `reports/evaluation_report.json`。

### LLM-enabled Evaluation（`run_llm_evaluation.py`）

- 通过 OpenRouter 真实调用配置的模型构建 Query Plan；
- 报告记录：`mode=llm`、`model`、`llm_calls`、`fallback_count`、`fallback_rate`；
- 未配置 `OPENROUTER_API_KEY` 时**明确 SKIP 且不生成报告**，禁止输出"0 calls / 100% pass"的误导结果；
- 输出 `reports/llm_evaluation_report.json`。

两条链路不混合：Deterministic Regression 是 GitHub Actions 的阻断门禁；Real
LLM E2E 只在手动 workflow 或本地显式运行时调用 API。未配置 Key 时脚本会明确
SKIP 且不生成报告，手动 workflow 会在执行前因缺少 Secret 失败。

### Relative Time Policy

`app/domain/time_range.py` 统一定义相对时间，参考日使用数据集最新日期：

- `过去/最近/近 N 个月`：包含当前月，共 N 个自然月；
- `本月`：当月 1 日至参考日；`上个月`：上一个完整自然月；
- `今年`：本年 1 月 1 日至参考日；`去年`：上一完整自然年；
- `过去/最近/近 N 天`：包含参考日的滚动 N 个日历日。

LLM 返回的相对日期会被该策略覆盖，避免模型把“过去 3 个月”漂移成 4 个月。

## 5. 常见疑问

**Q：为什么 Overall 100% 但 Executable 只算 27 个？**
A：8 个用例本来就是"应该拒绝/拦截"的（不支持 2 + 安全 4 + 越权 2）。让一个"应该被拒绝"的用例拉低执行成功率，指标就失去了意义。拒绝类用例的正确行为是"不执行"，它们已经计入 Unsupported Reject / Permission Safety / Security Defense 指标。

**Q：如何判断一次评测是否可信？**
A：先跑 `python3 scripts/verify_project_consistency.py`：报告 total 必须等于 Golden 数量、指标分母必须自洽、LLM 报告不得出现 0 calls / 100% pass。

## 5. CI 阻断门禁

Push / Pull Request 依次执行静态检查、compileall、完整单测、确定性 Golden
评测、一致性校验和 smoke test。任何一步返回非 0 都会阻断 CI；真实 LLM
评测不进入普通 PR 流程。
