# Render Free 部署说明

本文说明如何把当前 MVP 以 Render Free Web Service 形式部署，用于作品集演示、内部试用和低流量验证。

当前方案不接入 Supabase：应用使用本地 DuckDB 和固定种子的虚拟零售数据。Supabase 只有在后续需要持久化外部数据或审计记录时才需要引入。

## 1. 当前部署形态

```text
GitHub Repository
        ↓
Render Free Web Service（Docker）
        ↓
Streamlit Web Demo
        ↓
本地 DuckDB（启动时生成虚拟数据）
```

仓库已经提供 Docker 启动链路：

- `Dockerfile` 使用 Python 3.11 并安装 `requirements.txt`；
- `docker/entrypoint.sh` 在数据文件不存在时生成 DuckDB，然后启动 Streamlit；
- Streamlit 监听 `0.0.0.0:${PORT}`，未配置时回退到 8501；
- 健康检查路径为 `/_stcore/health`。

## 2. Render Free 的边界

Render Free 可以运行当前服务，但定位是 Demo / Hobby 环境，不是生产部署。官方限制包括：

- Free Web Service 连续 15 分钟没有访问后会休眠，下次访问需要冷启动；
- 每个 workspace 每月包含 750 个 Free instance hours；
- Free 实例约为 512MB 内存和 0.1 CPU；
- 文件系统是临时的，不能使用持久化磁盘；
- Render Free Postgres 数据库创建 30 天后会过期，因此本项目不使用它。

对当前项目的直接影响：

- DuckDB 在实例重启或重新部署后会重新生成，Demo 可以继续运行；
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
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
```

当前 Render 配置将 `PORT` 显式设为 8501，以便与 Docker 健康检查和现有默认值保持一致。入口脚本已经读取 `PORT`，本地未配置时回退到 8501。

仓库根目录的 `render.yaml` 已包含上述配置。可以在 Render 选择 Blueprint / Infrastructure as Code，从该文件创建服务；也可以按表格在控制台手动创建。

如果需要启用 OpenRouter，在 Render 的 Environment 中增加：

```text
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=<your-api-key>
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=<your-model-slug>
OPENROUTER_TIMEOUT_SECONDS=60
OPENROUTER_MAX_TOKENS=1200
OPENROUTER_HTTP_REFERER=https://retail-data-agent.onrender.com
OPENROUTER_APP_TITLE=Retail Data Agent
```

只有 `OPENROUTER_API_KEY` 是敏感配置，不能写入仓库；`OPENROUTER_MODEL` 使用 OpenRouter 的模型 slug。当前本地示例使用 `openrouter/free`，它会动态选择免费模型，速率限制、延迟和回答质量可能波动；如果需要稳定模型，应改为 OpenRouter 支持的具体模型 slug。其余变量是非敏感运行参数。保存环境变量后需要执行一次 **Manual Deploy → Deploy latest commit**，新进程才会读取配置。页面中看到“OpenRouter 已配置”后，在 Agent / 自然语言问数 / 智能报告中选择 OpenRouter 即可发起调用。

OpenRouter 的模型调用费用由 OpenRouter 账户承担，Render Free 不包含模型调用额度。LLM 只生成结构化查询计划或文字表达，权限、指标口径、SQL 和计算仍由本地链路负责；请求失败时应用会回退到确定性结果，并在 Agent 的技术详情中标记 fallback。

## 4. 部署后验证

部署成功后，打开 Render 分配的 `onrender.com` 地址，按以下顺序验证：

1. 页面能够打开，且首次加载允许有冷启动延迟；
2. 在 Agent Tab 提问：`为什么华东区域 11 月销售额下降了？`；
3. 切换为门店经理，验证越权请求返回 `DENY`；
4. 在“质量评测”Tab 查看确定性评测结果；
5. 观察 Deploy Logs 是否出现 DuckDB 初始化和 Streamlit 启动日志。

建议首次部署时先关闭 LLM，确认容器、端口、DuckDB 和权限链路正常后，再配置 OpenRouter API Key。

## 5. 常见问题

### 页面打不开或端口检查失败

确认 Render 环境变量为 `PORT=8501`，并确认服务日志显示监听 `0.0.0.0:8501`。Render Web Service 要求应用绑定 `0.0.0.0`，当前入口脚本已经满足这一点。

### 重启后审计记录消失

这是 Render Free 临时文件系统的预期行为，不是应用查询链路错误。需要长期保存时，应把审计写入外部数据库或对象存储；这属于后续架构改造。

### OpenRouter 模式失败

检查 `LLM_PROVIDER=openrouter`、`OPENROUTER_API_KEY`、`OPENROUTER_MODEL` 是否配置，以及 OpenRouter API 是否可访问。Render 和本项目的免费部署不包含模型调用费用。

### 是否需要 Supabase

当前不需要。接入 Supabase 需要把 DuckDB 数据源、SQL 执行器和审计存储改造成 PostgreSQL / API 适配层，不属于当前 MVP 的直接部署步骤。

## 6. 后续生产化方向

- 使用 Supabase 或其他受控数据库保存真实数据和审计记录；
- 将数据源适配从 DuckDB 扩展到 PostgreSQL；
- 增加持久化日志、备份、监控和告警；
- 根据访问量升级 Render 实例，避免 Free 休眠和资源限制。
