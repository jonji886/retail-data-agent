"""FastAPI API Boundary：复用 AgentApplicationService，不复制 Agent 逻辑。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from app.application import AgentApplicationService
from app.observability.runtime_logging import log_event


ROOT = Path(__file__).resolve().parents[1]
service = AgentApplicationService(ROOT)
app = FastAPI(title="Retail Data Agent API", version="1.0.0")


class QueryRequest(BaseModel):
    user_id: str = Field(default="user_hq", min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    use_llm: bool = True
    session_id: str = ""


def _response(state: Dict[str, Any], started: float) -> Dict[str, Any]:
    return {
        "run_id": state.get("trace_id"),
        "request_id": state.get("request_id"),
        "status": "success" if not state.get("error_type") else (
            "quota_exceeded" if state.get("error_type") == "QUOTA_EXCEEDED" else "failed"
        ),
        "intent": state.get("intent"),
        "answer": state.get("answer", ""),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "error_type": state.get("error_type"),
        "permission_decision": state.get("permission_decision"),
    }


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> Dict[str, Any]:
    ready_value = service.ready()
    return {"status": "ready" if ready_value else "not_ready", "datasource": ready_value}


@app.get("/metrics")
def metrics() -> Dict[str, Any]:
    return service.metrics.snapshot()


@app.post("/api/v1/query")
def query(payload: QueryRequest, request: Request) -> Dict[str, Any]:
    started = time.monotonic()
    client_ip = request.client.host if request.client else ""
    state = service.query(
        payload.question, user_id=payload.user_id, use_llm=payload.use_llm,
        session_id=payload.session_id or payload.user_id, client_ip=client_ip,
    )
    response = _response(state, started)
    log_event(
        "http_query_completed",
        surface="api_query",
        request_id=state.get("request_id"),
        trace_id=state.get("trace_id"),
        status=response["status"],
        error_type=response.get("error_type"),
        latency_ms=response["latency_ms"],
    )
    return response
