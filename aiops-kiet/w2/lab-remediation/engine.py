from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from features import extract_features
from retrieval import retrieve_and_vote
from decision import select_action


def decide(incident_path: Path, history_path: Path, actions_path: Path) -> dict:
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    history = json.loads(history_path.read_text(encoding="utf-8"))
    actions_catalog = yaml.safe_load(actions_path.read_text(encoding="utf-8"))
    vec = extract_features(incident)
    candidates = retrieve_and_vote(vec, history, top_k=5)
    decision = select_action(candidates, actions_catalog, query=vec)
    return {
        "incident_id": incident_path.stem,
        "selected_action": decision["selected_action"],
        "params": decision.get("params", {}),
        "confidence": decision["confidence"],
        "evidence": {
            "incident_id": incident["incident_id"],
            "trigger": incident.get("trigger_alert", {}),
            "feature_summary": {
                "log_count": vec["log_count"],
                "trace_count": vec["trace_count"],
                "metric_count": len(vec["metric_series"]),
                "top_log_keywords": sorted(vec["log_keywords"].items(), key=lambda kv: kv[1], reverse=True)[:8],
                "top_metric_anomalies": sorted(vec["metric_anomaly_strength"].items(), key=lambda kv: kv[1], reverse=True)[:8],
            },
            "retrieval": candidates,
            "decision": decision.get("evidence", {}),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")
    d = sub.add_parser("decide")
    d.add_argument("--incident", required=True)
    d.add_argument("--history", default="incidents_history.json")
    d.add_argument("--actions", default="actions.yaml")
    args = p.parse_args()
    if args.cmd == "decide":
        out = decide(Path(args.incident), Path(args.history), Path(args.actions))
        print(json.dumps(out, indent=2, ensure_ascii=False))
        with open("audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
