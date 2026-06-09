from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
GRAPH_PATH = BASE_DIR / "service_graph.json"
HISTORY_PATH = BASE_DIR / "incidents_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("aiops")

app = FastAPI(
    title="AIOps Incident Pipeline",
    version="1.0.0",
    description="Correlate alerts, infer root cause, and recommend actions.",
)


class Alert(BaseModel):
    id: str
    ts: str
    service: str
    metric: str
    severity: str
    value: float
    threshold: float
    labels: Optional[dict[str, Any]] = Field(default_factory=dict)


class IncidentRequest(BaseModel):
    alerts: list[Alert]


class Cluster(BaseModel):
    cluster_id: str
    alert_count: int
    services: list[str]
    time_range: list[str]


class RootCause(BaseModel):
    service: str
    confidence: float
    reasoning: str


class IncidentResponse(BaseModel):
    clusters: list[Cluster]
    root_cause: RootCause
    recommended_actions: list[str]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def stable_cluster_id(items: list[dict[str, Any]]) -> str:
    fingerprint = "|".join(
        f"{item.get('service', '')}:{item.get('metric', '')}:{item.get('severity', '')}"
        for item in sorted(items, key=lambda x: (x.get("service", ""), x.get("metric", ""), x.get("id", "")))
    )
    return "cluster-" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:10]


def correlate(alerts: list[dict[str, Any]], graph: dict[str, list[str]]) -> list[dict[str, Any]]:
    if not alerts:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for alert in alerts:
        grouped.setdefault(alert["service"], []).append(alert)

    clusters: list[dict[str, Any]] = []
    for service, service_alerts in grouped.items():
        related_services = [service]
        related_services.extend(graph.get(service, []))
        clusters.append(
            {
                "cluster_id": stable_cluster_id(service_alerts),
                "alert_count": len(service_alerts),
                "services": sorted(set(related_services)),
                "time_range": [service_alerts[0]["ts"], service_alerts[-1]["ts"]],
            }
        )

    clusters.sort(key=lambda item: item["alert_count"], reverse=True)
    return clusters


def run_rca(primary_cluster: dict[str, Any], alerts: list[dict[str, Any]], graph: dict[str, list[str]], history: list[dict[str, Any]]) -> dict[str, Any]:
    services = primary_cluster["services"]
    root_service = services[0] if services else "unknown"
    confidence = min(0.95, 0.55 + 0.1 * max(0, primary_cluster["alert_count"] - 1))

    if alerts:
        top_severity = max(alerts, key=lambda item: item.get("value", 0.0) - item.get("threshold", 0.0))
        root_service = top_severity["service"]
        if graph.get(root_service):
            root_service = root_service

    similar = []
    for item in history[:3]:
        similar.append(item.get("id", "INC-unknown"))

    return {
        "root_cause": root_service,
        "confidence": confidence,
        "reasoning": f"Service {root_service} appears in the densest cluster and has the largest deviation from threshold.",
        "actions": [
            f"Inspect {root_service} deployment and recent config changes",
            "Check downstream dependencies and error-budget burn",
            "If regression is confirmed, rollback the last safe version",
        ],
        "similar_incidents": similar,
    }


GRAPH = load_json(
    GRAPH_PATH,
    {
        "payment-svc": ["order-svc", "auth-svc"],
        "order-svc": ["inventory-svc"],
        "auth-svc": [],
    },
)
HISTORY = load_json(
    HISTORY_PATH,
    [
        {"id": "INC-2026-05-01", "summary": "Payment latency regression"},
        {"id": "INC-2026-05-14", "summary": "Order timeout spike"},
        {"id": "INC-2026-05-20", "summary": "Auth dependency slowdown"},
    ],
)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
    logger.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    graph_loaded = isinstance(GRAPH, dict) and len(GRAPH) > 0
    history_loaded = isinstance(HISTORY, list) and len(HISTORY) > 0
    if not graph_loaded or not history_loaded:
        raise HTTPException(status_code=503, detail="Dependencies not ready")
    return {
        "status": "ready",
        "graph_loaded": graph_loaded,
        "history_loaded": history_loaded,
        "graph_nodes": len(GRAPH),
        "history_items": len(HISTORY),
    }


def process_batch(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    clusters = correlate(alerts, GRAPH)
    if not clusters:
        return {
            "clusters": [],
            "root_cause": {"service": "unknown", "confidence": 0.0, "reasoning": "No alerts to process"},
            "recommended_actions": ["Collect more alerts and retry"],
        }

    primary = clusters[0]
    rca = run_rca(primary, alerts, GRAPH, HISTORY)
    return {
        "clusters": clusters,
        "root_cause": {
            "service": rca["root_cause"],
            "confidence": rca["confidence"],
            "reasoning": rca["reasoning"],
        },
        "recommended_actions": rca["actions"],
    }


@app.post("/incident", response_model=IncidentResponse)
def post_incident(req: IncidentRequest) -> IncidentResponse:
    try:
        result = process_batch([alert.model_dump() for alert in req.alerts])
        return IncidentResponse(**result)
    except Exception as exc:
        logger.exception("Pipeline failure")
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
