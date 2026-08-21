#!/bin/sh

set -eu

APP_PORT="${PORT:-8501}"

mkdir -p /app/data /app/reports

if [ ! -f /app/data/retail.duckdb ]; then
    echo "[data-agent] DuckDB not found; generating virtual retail data..."
    python scripts/generate_data.py
    python scripts/init_db.py
else
    echo "[data-agent] Reusing existing DuckDB: /app/data/retail.duckdb"
fi

echo "[data-agent] Starting Streamlit on 0.0.0.0:${APP_PORT}"
exec streamlit run app/web_app.py \
    --server.address=0.0.0.0 \
    --server.port="${APP_PORT}" \
    --server.headless=true \
    --browser.gatherUsageStats=false
