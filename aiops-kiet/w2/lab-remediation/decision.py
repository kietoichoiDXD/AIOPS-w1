from __future__ import annotations


def _build_action_map(actions_catalog: list[dict]) -> dict[str, dict]:
    return {a["name"]: a for a in actions_catalog}


def _default_params(action_name: str, query: dict) -> dict:
    svc = query.get("trigger_service") or ""
    if action_name == "rollback_service":
        return {"service": svc or "unknown", "target_version": "previous"}
    if action_name == "increase_pool_size":
        return {"service": svc or "unknown", "from_value": "50", "to_value": "100"}
    if action_name == "restart_pod":
        return {"service": svc or "unknown", "pod_selector": "default"}
    if action_name == "dns_config_rollback":
        return {"configmap_name": "dns-config", "target_revision": "previous"}
    if action_name == "network_policy_revert":
        return {"policy_name": "current"}
    if action_name == "page_oncall":
        return {"team": "platform-team"}
    return {}


def _dominant_log_service(query: dict) -> str:
    activity = query.get("service_activity", {})
    if not activity:
        return ""
    return max(activity.items(), key=lambda kv: kv[1].get("logs", 0))[0]


def _dominant_metric_service(query: dict) -> str:
    strengths = query.get("metric_anomaly_strength", {})
    if not strengths:
        return ""
    return max(strengths.items(), key=lambda kv: kv[1])[0].split(".", 1)[0]


def _escalate(reason: str, best_similarity: float, top_matches: list, votes: list, extra: dict | None = None) -> dict:
    ev = {"decision": reason, "best_similarity": round(best_similarity, 4), "top_matches": top_matches, "votes": votes}
    if extra:
        ev.update(extra)
    return {
        "selected_action": "page_oncall",
        "params": {"team": "platform-team"},
        "confidence": round(min(0.5, 0.25 + best_similarity / 2), 4),
        "evidence": ev,
    }


def select_action(candidates: dict, actions_catalog: list[dict], query: dict | None = None) -> dict:
    query = query or {}
    catalog = _build_action_map(actions_catalog)
    votes = candidates.get("action_votes", [])
    top_matches = candidates.get("top_matches", [])
    best_similarity = float(candidates.get("best_similarity", 0.0))
    gap = float(candidates.get("top_similarity_gap", 0.0))
    kw = query.get("log_keywords", {})
    log_svc = _dominant_log_service(query)
    metric_svc = _dominant_metric_service(query)
    trigger_svc = query.get("trigger_service") or ""

    if kw.get("tls", 0) or kw.get("certificate", 0):
        return _escalate("escalate_tls", best_similarity, top_matches, votes)

    if kw.get("dns", 0) or kw.get("nxdomain", 0):
        return _escalate("escalate_dns", best_similarity, top_matches, votes)

    if kw.get("oom", 0) or kw.get("memory", 0) or kw.get("gc_pause", 0) or kw.get("heap", 0):
        service = trigger_svc or metric_svc or log_svc or "unknown"
        return {
            "selected_action": "restart_pod",
            "params": {"service": service, "pod_selector": "default"},
            "confidence": round(min(0.78, 0.45 + best_similarity / 2), 4),
            "evidence": {
                "decision": "memory_restart",
                "best_similarity": round(best_similarity, 4),
                "keywords": {k: kw.get(k, 0) for k in ["oom", "memory", "gc_pause", "heap"]},
                "top_matches": top_matches, "votes": votes,
            },
        }

    if log_svc and metric_svc and log_svc != metric_svc and log_svc != trigger_svc and metric_svc != trigger_svc:
        return _escalate("escalate_disagreement", best_similarity, top_matches, votes)

    if not top_matches or best_similarity < 0.06:
        return {
            "selected_action": "page_oncall",
            "params": {"team": "platform-team"},
            "confidence": 0.18,
            "evidence": {"decision": "escalate_ood", "best_similarity": round(best_similarity, 4), "top_matches": top_matches, "votes": votes},
        }

    action_scores = {v["name"]: float(v["score"]) for v in votes}
    total = sum(max(0.0, s) for s in action_scores.values()) or 1.0
    ranked = sorted(action_scores.items(), key=lambda kv: kv[1], reverse=True)
    top_action = ranked[0][0] if ranked else "page_oncall"
    p_success = max(0.0, action_scores.get(top_action, 0.0)) / total

    if top_action == "page_oncall":
        return _escalate("escalate", best_similarity, top_matches, votes)

    action_meta = catalog.get(top_action)
    if not action_meta:
        return _escalate("escalate_unknown_action", best_similarity, top_matches, votes)

    blast = float(action_meta.get("blast_radius_services", 0))
    cost = float(action_meta.get("cost_min", 0))
    downtime = float(action_meta.get("downtime_min", 0))
    utility = 3.0 * p_success - 0.05 * cost - 0.08 * downtime - 0.12 * blast

    if blast >= 3 and p_success < 0.7:
        return _escalate("escalate_blast_radius", best_similarity, top_matches, votes,
                         {"p_success": round(p_success, 4), "utility": round(utility, 4)})
    if p_success < 0.25 or utility < 0.10:
        return _escalate("escalate_low_utility", best_similarity, top_matches, votes,
                         {"p_success": round(p_success, 4), "utility": round(utility, 4)})

    params = _default_params(top_action, query)
    if top_action in {"rollback_service", "increase_pool_size", "restart_pod"}:
        inferred = metric_svc or log_svc or trigger_svc
        if inferred:
            params["service"] = inferred
        if top_action == "rollback_service":
            params.setdefault("target_version", "previous")

    confidence = min(0.95, max(0.35, 0.45 + 0.4 * best_similarity + 0.1 * p_success + 0.05 * min(gap, 1.0)))
    return {
        "selected_action": top_action,
        "params": params,
        "confidence": round(confidence, 4),
        "evidence": {
            "decision": "auto_act",
            "best_similarity": round(best_similarity, 4),
            "top_similarity_gap": round(gap, 4),
            "p_success": round(p_success, 4),
            "utility": round(utility, 4),
            "top_matches": top_matches,
            "votes": votes,
        },
    }
