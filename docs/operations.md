# 运维与故障降级矩阵

本项目的默认目标是“可控失败、可追踪恢复”。用户看到稳定的业务提示，原始驱动错误只保留在受控日志的类型字段中；通过 `trace_id` 可回看节点、模型、数据源和耗时。

## Render 调用日志

Render 部署后，进入服务的 **Logs → Application logs**，搜索下面的 `event` 名称即可定位一次请求。AI 分析助手会在“查看分析依据”中显示 `request_id` 与 `trace_id`；FastAPI `/api/v1/query` 响应中的 `run_id` 就是 `trace_id`。将该 ID 粘贴到 Render 日志搜索框，可把入口、LLM、重试、故障切换和最终结果串起来。

| 事件 | 用途 |
|---|---|
| `natural_language_request_started` / `completed` / `failed` | AI 分析助手兼容入口及耗时、结果行数 |
| `agent_request_started` / `completed` / `failed` | Agent Runtime 总体结果、权限、Skill/LLM 调用数量 |
| `agent_request_rejected` / `application_request_completed` | Demo quota 拒绝和 Application Service 返回结果 |
| `http_query_completed` | FastAPI `/api/v1/query` 的 HTTP 返回状态和耗时 |
| `report_request_started` / `completed` / `failed` | 报告生成入口及耗时 |
| `llm_provider_request` | DeepSeek 或 OpenRouter 的每次实际请求、重试次数、HTTP 状态、错误类型、Token 与延迟 |
| `llm_fallback_started` / `skipped` | DeepSeek 失败后的 OpenRouter 切换或未配置原因 |
| `llm_request_completed` / `failed` | 一次 LLM 逻辑调用的最终 Provider、是否切换和最终错误 |

日志只输出 `request_id`、`trace_id`、Provider、模型、错误类型、状态、耗时和 Token 统计，不输出问题正文、Prompt、API Key、Authorization、数据库连接串或查询结果。Render 免费实例休眠或重启后，历史日志的保留和检索能力以 Render 当前方案为准；需要长期留存时应接入外部日志系统。

| Failure | Detection | Behaviour | User response | Trace/Audit |
|---|---|---|---|---|
| DeepSeek timeout / HTTP error | 客户端异常与超时 | 最多重试 `LLM_MAX_RETRIES`（0～2）；仍失败且配置 `OPENROUTER_API_KEY` 时，同一请求最多切换一次 OpenRouter；两个 Provider 都失败才确定性回退 | 优先返回 OpenRouter 结果，否则返回规则链路结果 | 记录实际 provider、model、`retry_count`、`fallback_used`、`fallback_from`、`fallback_reason` 与 `error_category` |
| 429 / model unavailable | HTTP 异常类型或请求失败 | DeepSeek 有限重试后切换 OpenRouter；不无限循环；OpenRouter 失败后确定性回退 | 优先返回 fallback 结果，否则提示使用确定性结果 | 记录 Provider failover 和最终 fallback reason |
| invalid JSON / structured output | JSON 与计划白名单校验失败 | 最多一次补请求，仍失败则走确定性解析 | 正常返回或明确拒答 | 记录 `LLMPlanError` 类型 |
| quota exceeded | session/IP/global 计数器 | 在调用 LLM 前停止请求 | 提示 Demo 额度已用尽 | `quota_exceeded`，不产生 LLM call |
| PostgreSQL unavailable | `/ready` 或数据源健康检查失败 | API 快速失败；不执行 Skill | 提示数据源暂不可用 | 记录 `DATA_SOURCE_UNAVAILABLE` |
| DB timeout | statement timeout / 驱动异常 | 返回受控查询超时错误 | 建议缩小范围后重试 | 记录 `query_timeout` |
| unsafe SQL | SELECT-only、单语句与危险词校验 | 阻止执行 | 返回安全策略拒绝 | 记录 reason code，不记录敏感凭证 |
| permission denied | Policy Layer | SQL 前拒绝，不调用业务 Tool | 返回权限不足 | 记录 `permission_decision=deny` |
| unknown metric / semantic config invalid | 启动校验或计划校验 | unknown metric 拒答；配置错误阻止启动 | 提示问题或服务不可用 | 记录 `INVALID_PLAN` / 启动日志 |
| empty result | Result Validation | 不生成数字或因果结论 | 说明没有数据 | 记录空结果状态 |
| evaluation regression | CI deterministic gate | 阻止合并 | 修复后重新评测 | 保存报告与失败 case |

## 运行检查

```bash
python scripts/validate_startup.py
python scripts/run_evaluation.py
python scripts/verify_project_consistency.py
```

公网 Demo 的 quota 是进程内轻量计数器，重启后清零；它适合保护免费模型额度，不宣称是分布式限流系统。Evaluation 直接调用 Agent Runtime，不经过 Demo quota。
