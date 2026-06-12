from __future__ import annotations

import math
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")
NUM_RE = re.compile(r"^\d+(\.\d+)?$")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _mask_token(tok: str) -> str:
    tok = tok.strip()
    if not tok:
        return ""
    if IP_RE.match(tok):
        return "<IP>"
    if NUM_RE.match(tok):
        return "<NUM>"
    if tok.startswith("202") and "T" in tok:
        return "<TS>"
    if tok.isdigit() or re.fullmatch(r"\d+[a-zA-Z%]*", tok):
        return "<NUM>"
    return tok.lower()


def _tokenize(text: str) -> list[str]:
    return [t for t in (_mask_token(x) for x in TOKEN_RE.findall(text)) if t]


def extract_features(incident: dict) -> dict:
    trigger = incident.get("trigger_alert", {})
    metrics = incident.get("metrics_window", {}).get("samples", {})
    traces = incident.get("traces", [])
    logs = incident.get("logs", [])
    topo = incident.get("topology", {})

    nodes = topo.get("nodes", [])
    edges = topo.get("edges", [])
    services = {trigger.get("service", "")}
    services.update(n.get("id", "") for n in nodes)
    services = {s for s in services if s}

    log_tokens = []
    keyword_hits = Counter()
    log_by_service = Counter()
    for row in logs:
        svc = row.get("svc") or row.get("service")
        if svc:
            log_by_service[svc] += 1
            services.add(svc)
        toks = _tokenize(row.get("msg", ""))
        log_tokens.extend(toks)
        for key in [
            "timeout", "pool", "deadlock", "oom", "dns", "tls", "certificate",
            "cache", "retry", "rebal", "latency", "error", "fail", "throttle",
            "lag", "drift", "partition", "rollback", "connection", "nxdomain",
            "informer", "stale", "5xx", "503", "429", "cpu", "memory", "heap",
            "gc_pause", "outofmemoryerror"
        ]:
            if key in row.get("msg", "").lower():
                keyword_hits[key] += 1

    trace_pairs = []
    trace_services = Counter()
    trace_error_sum = Counter()
    trace_p99_sum = Counter()
    for t in traces:
        fr = t.get("from")
        to = t.get("to")
        if fr:
            services.add(fr)
            trace_services[fr] += 1
        if to:
            services.add(to)
            trace_services[to] += 1
        if fr and to:
            trace_pairs.append((fr, to))
        err = float(t.get("error_count", 0) or 0)
        p99 = float(t.get("p99_ms", 0) or 0)
        if fr:
            trace_error_sum[fr] += err
            trace_p99_sum[fr] += p99
        if to:
            trace_error_sum[to] += err
            trace_p99_sum[to] += p99

    metric_series = {}
    metric_anomaly_strength = {}
    for key, series in metrics.items():
        vals = [float(v) for _, v in series]
        if not vals:
            continue
        svc, _ = key.split(".", 1)
        services.add(svc)
        metric_series[key] = {
            "n": len(vals), "mean": sum(vals) / len(vals),
            "min": min(vals), "max": max(vals),
            "last": vals[-1], "first": vals[0],
        }
        half = max(1, len(vals) // 2)
        baseline = vals[:half]
        mu = sum(baseline) / len(baseline)
        sigma = math.sqrt(sum((x - mu) ** 2 for x in baseline) / max(len(baseline), 1))
        metric_anomaly_strength[key] = abs(vals[-1] - mu) / max(sigma, 1e-6)

    edge_set = {(e.get("from"), e.get("to")) for e in edges if e.get("from") and e.get("to")}

    service_activity = {
        svc: {
            "logs": log_by_service.get(svc, 0),
            "traces": trace_services.get(svc, 0),
            "trace_error_sum": trace_error_sum.get(svc, 0.0),
            "trace_p99_sum": trace_p99_sum.get(svc, 0.0),
        }
        for svc in services
    }

    return {
        "incident_id": incident.get("incident_id"),
        "trigger_service": trigger.get("service"),
        "trigger_rule": trigger.get("rule_id"),
        "trigger_severity": trigger.get("severity"),
        "services": sorted(services),
        "log_tokens": log_tokens,
        "log_keywords": dict(keyword_hits),
        "trace_pairs": sorted(trace_pairs),
        "edge_set": sorted(edge_set),
        "metric_series": metric_series,
        "metric_anomaly_strength": metric_anomaly_strength,
        "service_activity": service_activity,
        "log_count": len(logs),
        "trace_count": len(traces),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
