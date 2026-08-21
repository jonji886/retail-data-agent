# 运维与故障降级矩阵

本项目的默认目标是“可控失败、可追踪恢复”。用户看到稳定的业务提示，原始驱动错误只保留在受控日志的类型字段中；通过 `trace_id` 可回看节点、模型、数据源和耗时。

| Failure | Detection | Behaviour | User response | Trace/Audit |
|---|---|---|---|---|
| OpenRouter timeout / HTTP error | 客户端异常与超时 | 最多重试 `LLM_MAX_RETRIES`（0～2），随后确定性回退 | 返回规则链路结果 | 记录 provider、model、retry_count、fallback |
| 429 / model unavailable | HTTP 异常类型或请求失败 | 有限重试，失败后回退；不无限循环 | 提示使用确定性结果 | 记录 fallback reason |
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
