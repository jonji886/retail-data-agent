FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY configs ./configs
COPY scripts ./scripts
COPY SPEC.md README.md .env.example ./
COPY docker ./docker

RUN chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /app/data /app/reports

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('PORT', '8501'); urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % port, timeout=4)"

ENTRYPOINT ["/bin/sh", "/app/docker/entrypoint.sh"]
