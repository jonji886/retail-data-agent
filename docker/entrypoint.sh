#!/bin/sh

set -eu

APP_PORT="${PORT:-8501}"

mkdir -p /app/data /app/reports

if [ "${DATA_SOURCE:-duckdb}" = "duckdb" ] && [ ! -f /app/data/retail.duckdb ]; then
    echo "[data-agent] DuckDB not found; generating virtual retail data..."
    python scripts/generate_data.py
    python scripts/init_db.py
elif [ "${DATA_SOURCE:-duckdb}" = "postgresql" ]; then
    echo "[data-agent] Using PostgreSQL data source; skipping local DuckDB initialization."
else
    echo "[data-agent] Reusing existing DuckDB: /app/data/retail.duckdb"
fi

python scripts/validate_startup.py

# 仅打印不含密钥的运行状态，便于 Render 日志确认实际 Provider，避免把
# Dashboard 中配置的凭证存在性误认为当前进程已经使用了 DeepSeek。
python -c 'from pathlib import Path; from app.llm.openrouter_client import provider_status; print("[data-agent] LLM status: %s" % provider_status(Path("/app")))' \
    || echo "[data-agent] Unable to inspect LLM provider status"

API_PORT_VALUE="${API_PORT:-8000}"
echo "[data-agent] Starting internal FastAPI on 127.0.0.1:${API_PORT_VALUE}"
uvicorn app.api:app --host 127.0.0.1 --port="${API_PORT_VALUE}" &

echo "[data-agent] Starting Streamlit on 0.0.0.0:${APP_PORT}"
exec streamlit run app/web_app.py \
    --server.address=0.0.0.0 \
    --server.port="${APP_PORT}" \
    --server.headless=true \
    --server.fileWatcherType=none \
    --browser.gatherUsageStats=false
