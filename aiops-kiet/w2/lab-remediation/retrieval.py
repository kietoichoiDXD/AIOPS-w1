from __future__ import annotations

from collections import Counter, defaultdict

from optional_helpers import parse_history_action, parse_metric_delta


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / max(len(a | b), 1)


def _counter_jaccard(a: Counter, b: Counter) -> float:
    if not a and not b:
        return 0.0
    keys = set(a) | set(b)
    inter = sum(min(a[k], b[k]) for k in keys)
    union = sum(max(a[k], b[k]) for k in keys)
    return inter / max(union, 1)


def _normalize_service_action(name: str, params: list[str]) -> dict:
    if name == "rollback_service":
        return {"name": name, "params": {"service": params[0] if params else "", "target_version": params[1] if len(params) > 1 else "previous"}}
    if name == "increase_pool_size":
        return {"name": name, "params": {"service": params[0] if params else "", "from_value": params[1] if len(params) > 1 else "50", "to_value": params[2] if len(params) > 2 else "100"}}
    if name == "restart_pod":
        return {"name": name, "params": {"service": params[0] if params else "", "pod_selector": params[1] if len(params) > 1 else "default"}}
    if name == "dns_config_rollback":
        return {"name": name, "params": {"configmap_name": params[0] if params else "dns-config", "target_revision": params[1] if len(params) > 1 else "previous"}}
    if name == "network_policy_revert":
        return {"name": name, "params": {"policy_name": params[0] if params else "current"}}
    if name == "page_oncall":
        return {"name": name, "params": {"team": params[0] if params else "platform-team"}}
    return {"name": name, "params": {"args": params}}


def _history_features(entry: dict) -> dict:
    log_tokens = []
    for sig in entry.get("log_signatures", []):
        log_tokens.extend(sig.lower().split())
    trace_pairs = []
    metric_keys = []
    for t in entry.get("trace_signatures", []):
        fr, to = t.get("from"), t.get("to")
        if fr and to:
            trace_pairs.append((fr, to))
    for m in entry.get("metric_signatures", []):
        metric_keys.append(f"{m.get('service')}.{m.get('metric')}")
        parse_metric_delta(m.get("delta", "0 -> 0"))
    actions = []
    for a in entry.get("actions_taken", []):
        parsed = parse_history_action(a)
        actions.append(_normalize_service_action(parsed["name"], parsed["params"]))
    return {
        "id": entry.get("id"),
        "root_cause_class": entry.get("root_cause_class"),
        "affected_services": set(entry.get("affected_services", [])),
        "log_tokens": Counter(log_tokens),
        "trace_pairs": set(trace_pairs),
        "metric_keys": set(metric_keys),
        "actions": actions,
        "outcome": entry.get("outcome", "partial"),
    }


def similarity(query: dict, hist: dict) -> float:
    q_logs = Counter(query.get("log_tokens", []))
    q_traces = set(query.get("trace_pairs", []))
    q_metrics = set(query.get("metric_series", {}))
    q_services = set(query.get("services", []))

    log_sim = _counter_jaccard(q_logs, hist["log_tokens"])
    trace_sim = _jaccard(q_traces, hist["trace_pairs"])
    metric_sim = _jaccard(q_metrics, hist["metric_keys"])
    service_sim = _jaccard(q_services, hist["affected_services"])

    trigger = query.get("trigger_service")
    trigger_bonus = 0.12 if trigger and trigger in hist["affected_services"] else 0.0

    return 0.4 * log_sim + 0.28 * trace_sim + 0.2 * metric_sim + 0.12 * service_sim + trigger_bonus


def retrieve_and_vote(query: dict, history: list[dict], top_k: int = 5) -> dict:
    prepared = [_history_features(h) for h in history]
    scored = []
    for h in prepared:
        sim = similarity(query, h)
        outcome_w = 1.0 if h["outcome"] == "success" else 0.6 if h["outcome"] == "partial" else 0.2
        scored.append((sim, outcome_w, h))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = scored[:top_k]
    votes = defaultdict(float)
    evidence = []
    for rank, (sim, outcome_w, h) in enumerate(top, start=1):
        rank_weight = 1.0 / rank
        for action in h["actions"]:
            act_name = action["name"]
            page_penalty = 0.35 if act_name == "page_oncall" else 1.0
            weight = sim * rank_weight * outcome_w * page_penalty
            votes[act_name] += weight
            evidence.append({
                "history_id": h["id"],
                "similarity": round(sim, 4),
                "rank": rank,
                "outcome_weight": outcome_w,
                "action": action,
                "vote_weight": round(weight, 4),
                "outcome": h["outcome"],
                "root_cause_class": h["root_cause_class"],
            })

    ranking = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "top_matches": [
            {"history_id": h["id"], "similarity": round(sim, 4), "rank": rank,
             "outcome": h["outcome"], "actions": h["actions"], "root_cause_class": h["root_cause_class"]}
            for rank, (sim, _, h) in enumerate(top, start=1)
        ],
        "action_votes": [{"name": name, "score": round(score, 4)} for name, score in ranking],
        "raw_votes": dict(votes),
        "evidence": evidence,
        "best_similarity": top[0][0] if top else 0.0,
        "top_similarity_gap": (top[0][0] - top[1][0]) if len(top) > 1 else 1.0,
    }
