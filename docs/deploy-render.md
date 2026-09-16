# Render Free 部署说明

本文说明如何把 v1.0 Portfolio MVP 以 Render Free Web Service + Supabase PostgreSQL 形式部署，用于作品集演示、内部试用和低流量验证。

## 1. 当前部署形态

```text
GitHub Repository
        ↓
Render Free Web Service（Docker）
        ↓
Streamlit + 内部 FastAPI
        ↓
Supabase PostgreSQL（业务数据）
```

仓库已经提供 Docker 启动链路：

- `Dockerfile` 使用 Python 3.11 并安装 `requirements.txt`；
- `docker/entrypoint.sh` 在 DuckDB 模式生成本地数据，在 PostgreSQL 模式跳过本地初始化并执行启动校验；
- Streamlit 监听 `0.0.0.0:${PORT}`，未配置时回退到 8501；
- 健康检查路径为 `/_stcore/health`。

## 2. Render Free 的边界

Render Free 可以运行当前服务，但定位是 Demo / Hobby 环境，不是生产部署。官方限制包括：

- Free Web Service 连续 15 分钟没有访问后会休眠，下次访问需要冷启动；
- 每个 workspace 每月包含 750 个 Free instance hours；
- Free 实例约为 512MB 内存和 0.1 CPU；
- 文件系统是临时的，不能使用持久化磁盘；
- 因 Render Free 数据库有生命周期限制，业务数据使用 Supabase。

对当前项目的直接影响：

- PostgreSQL 数据由 Supabase 持久化；本地 DuckDB 仍可在重启后重新生成；
- `data/runtime/audit.jsonl` 和 `data/runtime/badcases.jsonl` 属于本地运行时文件，重启后可能丢失；
- 不应把 Render Free 上的审计记录或真实业务数据当作长期存储；
- 首次打开页面或休眠唤醒后响应较慢是预期行为。

详见 [Render Free 实例说明](https://render.com/docs/free) 和 [Render 实例规格](https://render.com/docs/compute-plans)。

## 3. Render 控制台配置

在 Render 控制台创建 `New → Web Service`：

| 配置项 | 值 |
|---|---|
| Repository | 当前 GitHub 仓库 |
| Runtime | Docker |
| Root Directory | `/` |
| Branch | `main`（或实际部署分支） |
| Instance Type | `Free` |
| Health Check Path | `/_stcore/health` |
| Start Command | Docker 模式下留空，使用 Dockerfile 的 `ENTRYPOINT` |

添加环境变量：

```text
PORT=8501
API_PORT=8000
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
DATA_SOURCE=postgresql
DATABASE_URL=<supabase-postgresql-url>
```

当前 Render 配置将 `PORT` 显式设为 8501，以便与 Docker 健康检查和现有默认值保持一致。入口脚本已经读取 `PORT`，本地未配置时回退到 8501。

仓库根目录的 `render.yaml` 已包含上述配置。可以在 Render 选择 Blueprint / Infrastructure as Code，从该文件创建服务；也可以按表格在控制台手动创建。

在 Supabase 初始化数据后，再在 Render 的 Environment 中配置：

```text
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<your-api-key>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MAIN_MODEL=deepseek-flash
# Optional role models
DEEPSEEK_ROUTER_MODEL=<router-model>
DEEPSEEK_REASONING_MODEL=<reason-model>
# Or choose Qwen instead
# LLM_PROVIDER=qwen
# QWEN_API_KEY=<your-api-key>
# QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# QWEN_MAIN_MODEL=qwen3.8-flash
EVAL_LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=1200
LLM_MAX_RETRIES=1
DEMO_RATE_LIMIT_ENABLED=true
DEMO_SESSION_LIMIT=10
DEMO_IP_DAILY_LIMIT=20
DEMO_GLOBAL_DAILY_LIMIT=40
```

`DATABASE_URL`、Provider API Key 和 `EVAL_LLM_MODEL` 不能写入仓库。保存环境变量后需要执行一次 **Manual Deploy → Deploy latest commit**，新进程才会读取配置。治理后台会显示当前 Provider、首选模型、可用性和备选模型状态。已有 SiliconFlow 环境仍可继续使用 `LLM_PROVIDER=siliconflow` 与 `SILICONFLOW_API_KEY`。

Render 生产容器通过 `--server.fileWatcherType=none` 关闭 Streamlit 开发态文件监听。这样不影响用户点击后的脚本重跑，但可以避免 Free 实例因 watchdog / inotify 实例上限导致页面交互异常；本地开发仍可直接使用默认文件监听。

模型调用费用由所选 Provider 账户承担，Render Free 不包含模型调用额度。无法由确定性规则识别的意图才会调用 Router；文本链路先走 Main，按 `LLM_MAX_RETRIES` 有限重试仍超时或报错时切换 Reason；Reason 也失败后才回退确定性结果。Vision 目前仅作为多模态配置预留，不参与文本 fallback。LLM 只生成结构化查询计划或文字表达，权限、指标口径、SQL 和计算仍由本地链路负责；治理后台会标记实际角色、模型与 fallback reason。

## 4. 部署后验证

部署成功后，打开 Render 分配的 `onrender.com` 地址，按以下顺序验证：

1. 页面能够打开，且首次加载允许有冷启动延迟；
2. 在 AI 分析助手提问：`为什么华东区域 11 月销售额下降了？`，点击一条推荐追问确认自动继续；
3. 切换为门店经理，验证越权请求返回 `DENY`；
4. 在治理后台的 Evaluation 视图查看确定性评测结果；
5. 观察 Deploy Logs 是否出现 PostgreSQL 启动校验和 Streamlit 启动日志。

建议首次部署时先完成 Supabase 初始化并关闭 LLM，确认容器、端口、PostgreSQL 和权限链路正常后，再配置所选 Provider API Key；随后用故障注入或临时不可用 Main 验证 Reason failover 记录，并确认 Router 只影响无法确定意图的请求。

## 5. 常见问题

### 页面打不开或端口检查失败

确认 Render 环境变量为 `PORT=8501`，并确认服务日志显示监听 `0.0.0.0:8501`。Render Web Service 要求应用绑定 `0.0.0.0`，当前入口脚本已经满足这一点。

### 重启后审计记录消失

这是 Render Free 临时文件系统的预期行为，不是应用查询链路错误。需要长期保存时，应把审计写入外部数据库或对象存储；这属于后续架构改造。

### 当前 Model Provider 首选模型失败

检查 `LLM_PROVIDER`、所选 Provider 对应的 API Key、Base URL 和角色模型配置是否匹配（DeepSeek 使用 `DEEPSEEK_*`，Qwen 使用 `QWEN_*`，SiliconFlow 使用 `SILICONFLOW_*`），以及所选 API 是否可访问；查看 Trace 中的 `role`、`fallback_used`、`fallback_from_model`、`fallback_model` 和 `fallback_reason`。Render 和本项目的免费部署不包含模型调用费用。

### 如何初始化 Supabase

本地准备好 `.env` 后执行：

```bash
python scripts/generate_data.py
DATA_SOURCE=postgresql python scripts/init_postgres.py
```

脚本会创建表、视图、索引，导入固定 Demo 数据并输出校验行数。只重灌数据可使用 `python scripts/seed_postgres.py`。

## 6. 后续生产化方向

- 将审计从本地 JSONL 迁移到受控持久化存储；
- 根据访问量升级为持久化、分布式 quota 与监控方案；
- 增加持久化日志、备份、监控和告警；
- 根据访问量升级 Render 实例，避免 Free 休眠和资源限制。
