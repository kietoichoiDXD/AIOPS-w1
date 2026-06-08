from __future__ import annotations

import argparse
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
import uvicorn


BASE_DIR = Path(__file__).resolve().parent
ALERTS_FILE = BASE_DIR / "alerts.jsonl"
LOG_FILE = BASE_DIR / "pipeline.log"

WINDOW_SIZE = 50
WARMUP_POINTS = 20
M_OUT_OF_N = 3
M_OUT_OF_N_WINDOW = 5
ALERT_SUPPRESSION_SECONDS = 60
FAULT_PRIORITY = {
    "dependency_timeout": 3,
    "memory_leak": 2,
    "traffic_spike": 1,
}

ROLLING_KEYS = (
    "memory_utilization",
    "http_p99_latency_ms",
    "upstream_timeout_rate",
    "queue_depth",
)

app = FastAPI(title="ShopX Streaming Anomaly Pipeline")


def setup_logger() -> logging.Logger:
    logger = logging.getLogger("pipeline")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


LOGGER = setup_logger()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class RollingStats:
    values: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW_SIZE))

    def add(self, value: float) -> None:
        self.values.append(value)

    def mean(self) -> float | None:
        if len(self.values) < 5:
            return None
        return float(np.mean(self.values))

    def std(self) -> float | None:
        if len(self.values) < 5:
            return None
        s = float(np.std(self.values, ddof=0))
        return s if s > 1e-9 else 1.0

    def last(self) -> float | None:
        return float(self.values[-1]) if self.values else None

    def slope(self, lookback: int = 10) -> float | None:
        if len(self.values) < lookback + 1:
            return None
        return float(self.values[-1] - self.values[-1 - lookback])


@dataclass
class PipelineState:
    request_count: int = 0
    metrics_history: dict[str, RollingStats] = field(default_factory=dict)
    anomaly_flags_by_type: dict[str, deque[int]] = field(
        default_factory=lambda: {
            "memory_leak": deque(maxlen=M_OUT_OF_N_WINDOW),
            "traffic_spike": deque(maxlen=M_OUT_OF_N_WINDOW),
            "dependency_timeout": deque(maxlen=M_OUT_OF_N_WINDOW),
        }
    )
    last_alert_time_by_type: dict[str, datetime] = field(default_factory=dict)
    baseline_ready: bool = False
    last_fault_scores: dict[str, int] = field(
        default_factory=lambda: {
            "memory_leak": 0,
            "traffic_spike": 0,
            "dependency_timeout": 0,
        }
    )

    def metric(self, key: str) -> RollingStats:
        if key not in self.metrics_history:
            self.metrics_history[key] = RollingStats()
        return self.metrics_history[key]

    def update(self, payload_metrics: dict[str, Any]) -> dict[str, float]:
        memory = safe_float(payload_metrics.get("memory_usage_bytes"))
        limit = max(safe_float(payload_metrics.get("memory_limit_bytes"), 1.0), 1.0)
        cpu = safe_float(payload_metrics.get("cpu_usage_percent"))
        rps = safe_float(payload_metrics.get("http_requests_per_sec"))
        latency = safe_float(payload_metrics.get("http_p99_latency_ms"))
        five_x = safe_float(payload_metrics.get("http_5xx_rate"))
        gc = safe_float(payload_metrics.get("jvm_gc_pause_ms_avg"))
        queue = safe_float(payload_metrics.get("queue_depth"))
        timeout = safe_float(payload_metrics.get("upstream_timeout_rate"))

        derived = {
            "memory_utilization": memory / limit * 100.0,
            "cpu_usage_percent": cpu,
            "http_requests_per_sec": rps,
            "http_p99_latency_ms": latency,
            "http_5xx_rate": five_x,
            "jvm_gc_pause_ms_avg": gc,
            "queue_depth": queue,
            "upstream_timeout_rate": timeout,
        }

        for key, value in derived.items():
            self.metric(key).add(value)

        self.request_count += 1
        if self.request_count >= WARMUP_POINTS:
            self.baseline_ready = True

        return derived

    def zscore(self, key: str, value: float) -> float | None:
        stats = self.metrics_history.get(key)
        if not stats:
            return None
        mean = stats.mean()
        std = stats.std()
        if mean is None or std is None:
            return None
        return (value - mean) / std

    def trend_up(self, key: str, lookback: int = 5) -> bool:
        stats = self.metrics_history.get(key)
        if not stats or len(stats.values) < lookback + 1:
            return False
        values = list(stats.values)
        return values[-1] > values[-lookback - 1]


STATE = PipelineState()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = datetime.now(timezone.utc)
    response = await call_next(request)
    elapsed_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000.0
    LOGGER.info("http %s %s status=%s elapsed_ms=%.2f", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


def classify_severity(derived: dict[str, float]) -> str:
    if (
        derived["memory_utilization"] > 85
        or derived["upstream_timeout_rate"] > 30
        or derived["http_5xx_rate"] > 10
        or derived["http_p99_latency_ms"] > 1000
    ):
        return "critical"
    return "warning"


def detect_memory_leak(derived: dict[str, float]) -> tuple[bool, str]:
    mem = derived["memory_utilization"]
    gc = derived["jvm_gc_pause_ms_avg"]
    latency = derived["http_p99_latency_ms"]
    mem_z = STATE.zscore("memory_utilization", mem)
    gc_z = STATE.zscore("jvm_gc_pause_ms_avg", gc)
    latency_z = STATE.zscore("http_p99_latency_ms", latency)

    score = 0
    if mem > 80:
        score += 2
    if mem_z is not None and abs(mem_z) > 2.5:
        score += 1
    if gc > 25:
        score += 1
    if gc_z is not None and abs(gc_z) > 2:
        score += 1
    if latency > 80:
        score += 1
    if STATE.trend_up("memory_utilization"):
        score += 2
    if STATE.trend_up("jvm_gc_pause_ms_avg"):
        score += 1

    return score >= 4, f"memory_utilization={mem:.1f}%, gc={gc:.1f}ms, latency={latency:.1f}ms"


def detect_traffic_spike(derived: dict[str, float], logs: list[dict[str, Any]]) -> tuple[bool, str]:
    rps = derived["http_requests_per_sec"]
    queue = derived["queue_depth"]
    latency = derived["http_p99_latency_ms"]
    log_text = " ".join(str(log.get("message", "")).lower() for log in logs)
    has_timeout_noise = "timeout" in log_text or "circuit breaker" in log_text
    rps_z = STATE.zscore("http_requests_per_sec", rps)
    queue_z = STATE.zscore("queue_depth", queue)
    latency_z = STATE.zscore("http_p99_latency_ms", latency)

    score = 0
    if rps > 180:
        score += 2
    if rps_z is not None and abs(rps_z) > 2:
        score += 1
    if queue > 18:
        score += 1
    if queue_z is not None and abs(queue_z) > 2:
        score += 1
    if latency > 90:
        score += 1
    if latency_z is not None and abs(latency_z) > 2:
        score += 1
    if STATE.trend_up("http_requests_per_sec"):
        score += 1
    if STATE.trend_up("queue_depth"):
        score += 1
    if STATE.trend_up("http_p99_latency_ms"):
        score += 1
    if has_timeout_noise:
        score -= 2

    return score >= 4, f"rps={rps:.1f}, queue={queue:.0f}, latency={latency:.1f}ms"


def detect_dependency_timeout(derived: dict[str, float], logs: list[dict[str, Any]]) -> tuple[bool, str]:
    timeout = derived["upstream_timeout_rate"]
    latency = derived["http_p99_latency_ms"]
    five_x = derived["http_5xx_rate"]
    timeout_z = STATE.zscore("upstream_timeout_rate", timeout)
    latency_z = STATE.zscore("http_p99_latency_ms", latency)
    five_x_z = STATE.zscore("http_5xx_rate", five_x)

    log_text = " ".join(str(log.get("message", "")).lower() for log in logs)
    has_timeout_log = "timeout" in log_text or "circuit breaker" in log_text

    score = 0
    if timeout > 5:
        score += 2
    if timeout_z is not None and abs(timeout_z) > 2:
        score += 1
    if latency > 120:
        score += 1
    if latency_z is not None and abs(latency_z) > 2:
        score += 1
    if five_x > 2:
        score += 1
    if five_x_z is not None and abs(five_x_z) > 2:
        score += 1
    if STATE.trend_up("upstream_timeout_rate"):
        score += 1
    if STATE.trend_up("http_p99_latency_ms"):
        score += 1
    if STATE.trend_up("http_5xx_rate"):
        score += 1
    if has_timeout_log:
        score += 2

    return score >= 4, f"timeout={timeout:.2f}%, latency={latency:.1f}ms, 5xx={five_x:.2f}%"


def classify_fault(derived: dict[str, float], logs: list[dict[str, Any]]) -> dict[str, tuple[bool, str]]:
    return {
        "memory_leak": detect_memory_leak(derived),
        "traffic_spike": detect_traffic_spike(derived, logs),
        "dependency_timeout": detect_dependency_timeout(derived, logs),
    }


def update_m_out_of_n(fault_type: str, flag: bool) -> bool:
    history = STATE.anomaly_flags_by_type[fault_type]
    history.append(1 if flag else 0)
    return sum(history) >= M_OUT_OF_N


def pick_fault_type(candidates: dict[str, tuple[bool, str]], derived: dict[str, float], logs: list[dict[str, Any]]) -> tuple[str, bool, str, dict[str, int]]:
    scores: dict[str, int] = {}
    evidence_bonus: dict[str, int] = {}
    log_text = " ".join(str(log.get("message", "")).lower() for log in logs)
    has_timeout_log = "timeout" in log_text or "circuit breaker" in log_text
    has_overload_log = "overloaded" in log_text

    for fault_type, (detected, reason) in candidates.items():
        score = sum(STATE.anomaly_flags_by_type[fault_type])
        if detected:
            score += 2
        if fault_type == "dependency_timeout":
            if has_timeout_log:
                score += 3
                evidence_bonus[fault_type] = 3
        elif fault_type == "traffic_spike":
            if has_overload_log:
                score += 2
                evidence_bonus[fault_type] = 2
            if derived["http_requests_per_sec"] > 180:
                score += 2
        elif fault_type == "memory_leak":
            if derived["memory_utilization"] > 80:
                score += 2
        scores[fault_type] = score

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            item[1],
            FAULT_PRIORITY[item[0]],
        ),
        reverse=True,
    )
    fault_type = ranked[0][0]
    detected, reason = candidates[fault_type]
    return fault_type, detected, reason, scores


def should_suppress(fault_type: str, timestamp: str) -> bool:
    current = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    last = STATE.last_alert_time_by_type.get(fault_type)
    if last is None:
        return False
    return (current - last).total_seconds() < ALERT_SUPPRESSION_SECONDS


def fire_alert(timestamp: str, fault_type: str, severity: str, message: str) -> dict[str, Any]:
    alert = {
        "timestamp": timestamp,
        "type": fault_type,
        "severity": severity,
        "message": message,
    }
    append_jsonl(ALERTS_FILE, alert)
    STATE.last_alert_time_by_type[fault_type] = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    LOGGER.info("alert fired type=%s severity=%s message=%s", fault_type, severity, message)
    return alert


@app.post("/ingest")
async def ingest(request: Request):
    payload = await request.json()
    timestamp = str(payload["timestamp"])
    metrics = payload["metrics"]
    logs = payload.get("logs", [])

    derived = STATE.update(metrics)
    LOGGER.info("request=%d ingest timestamp=%s", STATE.request_count, timestamp)

    if not STATE.baseline_ready:
        return {"status": "warming_up", "request_count": STATE.request_count}

    candidates = classify_fault(derived, logs)
    for fault_type, (detected, _) in candidates.items():
        update_m_out_of_n(fault_type, detected)

    fault_type, detected, reason, scores = pick_fault_type(candidates, derived, logs)
    fire_now = sum(STATE.anomaly_flags_by_type[fault_type]) >= M_OUT_OF_N

    if fire_now and not should_suppress(fault_type, timestamp):
        severity = classify_severity(derived)
        alert_message = {
            "memory_leak": "Memory usage growing abnormally",
            "traffic_spike": "Traffic spike detected from RPS, queue depth and latency growth",
            "dependency_timeout": "Dependency timeout detected from timeout rate and log evidence",
        }[fault_type]
        alert = fire_alert(timestamp, fault_type, severity, alert_message)
        return {"status": "alerted", "fault_type": fault_type, "alert": alert}

    if candidates[fault_type][0]:
        LOGGER.info("anomaly detected type=%s score=%s reason=%s", fault_type, scores.get(fault_type, 0), reason)

    return {"status": "ok", "fault_type": fault_type, "detected": candidates[fault_type][0]}


def main() -> None:
    parser = argparse.ArgumentParser(description="ShopX streaming anomaly pipeline")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
