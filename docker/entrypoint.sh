#!/bin/sh

set -eu

mkdir -p /app/data /app/reports

if [ ! -f /app/data/retail.duckdb ]; then
    echo "[data-agent] DuckDB not found; generating virtual retail data..."
    python scripts/generate_data.py
    python scripts/init_db.py
else
    echo "[data-agent] Reusing existing DuckDB: /app/data/retail.duckdb"
fi

echo "[data-agent] Starting Streamlit on 0.0.0.0:8501"
exec streamlit run app/web_app.py \
    --server.address=0.0.0.0 \
    --server.port=8501 \
    --server.headless=true \
    --browser.gatherUsageStats=false

