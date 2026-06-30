"""
materialize_feature_store.py — build CONCRETE DynamoDB items for
`finops-feature-store-{env}` from real CUR + metrics, per contract Phụ lục F.

Reuses the ENGINE's own `_compute_rolling_stats` so every rolling-stat value is
exactly what the Engine expects to read back — no drift between writer and reader.

Outputs (to tools/feature_store_out/):
  create_table.sh             aws CLI to create the table (PK=resource_id, SK=date, TTL)
  feature_store_seed.json     batch-write-item payload (real items) — ready to load
  load_seed.sh                aws CLI to batch-write the seed
  feature_store_sample.md     human-readable table of the same items

Run (from engine-skeleton/):
  python tools/materialize_feature_store.py --env dev
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ml.statistical_detect_service import _compute_rolling_stats  # noqa: E402
REPO = ROOT.parents[2]
DATA = REPO / "Capstone_Phase2_AI" / "data" / "Datanew"
if not (DATA / "new_cur_line_items.csv").exists():
    DATA = REPO / "AIO2" / "metrics_data"          # fallback to the same June files
OUT = ROOT / "tools" / "feature_store_out"
OUT.mkdir(parents=True, exist_ok=True)

# Resources to materialize as a concrete seed (the labelled June anomaly examples).
SEED_RESOURCES = [
    "arn:aws:rds:us-east-1:acct:db:db-1066",                 # T2 anomaly (prod-payments)
    "arn:aws:rds:us-east-1:acct:db:db-staging-orphan-01",    # T1 benign (staging)
]


def _daily_metrics() -> pd.DataFrame:
    m = pd.read_csv(DATA / "new_metrics.csv",
                    usecols=["timestamp", "resource_id", "cpu_percent", "memory_mib",
                             "network_in_bytes", "network_out_bytes", "disk_io_ops",
                             "database_connections", "gpu_utilization"])
    m["date"] = pd.to_datetime(m["timestamp"]).dt.normalize()
    g = m.groupby(["resource_id", "date"])
    agg = g.agg(
        cpu_mean=("cpu_percent", "mean"),
        active=("cpu_percent", lambda s: float((s > 5).mean())),
        memory_mib=("memory_mib", "mean"),
        network_in_bytes=("network_in_bytes", "mean"),
        network_out_bytes=("network_out_bytes", "mean"),
        disk_io_ops=("disk_io_ops", "mean"),
        database_connections=("database_connections", "mean"),
        gpu_utilization=("gpu_utilization", "mean"),
    ).reset_index()
    return agg


def _cost() -> pd.DataFrame:
    cur = pd.read_csv(DATA / "new_cur_line_items.csv")
    cur["date"] = pd.to_datetime(cur["line_item_usage_start_date"]).dt.tz_localize(None).dt.normalize()
    g = (cur.groupby(["line_item_resource_id", "date", "line_item_usage_account_id",
                      "line_item_product_code", "line_item_usage_type", "pricing_unit"], dropna=False)
            .agg(cost=("line_item_unblended_cost", "sum"),
                 usage_amount=("line_item_usage_amount", "sum"),
                 team=("resource_tags_user_team", "first"),
                 owner=("resource_tags_user_owner", "first"),
                 env=("resource_tags_user_environment", "first"),
                 cost_center=("resource_tags_user_cost_center", "first"))
            .reset_index())
    return g


def _num(v):
    return {"N": str(round(float(v), 4))} if v is not None and not pd.isna(v) else {"NULL": True}


def _s(v):
    return {"S": str(v)} if v is not None and not pd.isna(v) and str(v) != "" else {"NULL": True}


def build_items(env: str) -> list[dict]:
    cost = _cost()
    met = _daily_metrics()
    # peer median per (account, product, date)
    peer = cost.groupby(["line_item_usage_account_id", "line_item_product_code", "date"])["cost"].median()

    items: list[dict] = []
    ttl = int(time.time()) + 35 * 86400
    for rid in SEED_RESOURCES:
        sub = cost[cost["line_item_resource_id"] == rid].sort_values("date")
        history: list[float] = []
        for row in sub.itertuples():
            c = float(row.cost)
            stats = _compute_rolling_stats(c, history)
            age_days = len(history) + 1
            history.append(c)

            mrow = met[(met["resource_id"] == rid) & (met["date"] == row.date)]
            m = mrow.iloc[0] if len(mrow) else None
            usage_density = float(m["active"]) if m is not None else 0.5
            cpu_mean = float(m["cpu_mean"]) if m is not None else None

            peer_med = float(peer.get((row.line_item_usage_account_id, row.line_item_product_code, row.date), c))
            peer_ratio = c / (peer_med + 1e-6)
            cost_ratio = c / (stats["rolling_avg"] + 1e-6)
            abs_spike = max(0.0, c - 3 * stats["rolling_std"])

            item = {
                "resource_id": {"S": rid},
                "date": {"S": row.date.strftime("%Y-%m-%d")},
                "line_item_usage_account_id": {"S": str(row.line_item_usage_account_id)},
                "line_item_product_code": {"S": str(row.line_item_product_code)},
                "line_item_usage_type": {"S": str(row.line_item_usage_type)},
                "pricing_unit": {"S": str(row.pricing_unit)},
                "line_item_usage_amount": _num(row.usage_amount),
                "line_item_unblended_cost": _num(c),
                "is_estimated": {"BOOL": False},
                # rolling stats (engine parity)
                "rolling_avg": _num(stats["rolling_avg"]),
                "rolling_std": _num(stats["rolling_std"]),
                "rolling_median": _num(stats["rolling_median"]),
                "rolling_mad": _num(stats["rolling_mad"]),
                "slope_14d": _num(stats["slope_14d"]),
                "cost_pct_change_28d": _num(stats["cost_pct_change_28d"]),
                "cost_ratio_to_7d_avg": _num(cost_ratio),
                "absolute_cost_spike": _num(abs_spike),
                "peer_ratio": _num(peer_ratio),
                "age_days": _num(age_days),
                # operational metrics
                "cpu_mean": _num(cpu_mean),
                "usage_density_24h": _num(usage_density),
                "memory_mib": _num(m["memory_mib"]) if m is not None else {"NULL": True},
                "database_connections": _num(m["database_connections"]) if m is not None else {"NULL": True},
                "gpu_utilization": _num(m["gpu_utilization"]) if m is not None else {"NULL": True},
                # tags
                "resource_tags_user_environment": _s(row.env),
                "resource_tags_user_team": _s(row.team),
                "resource_tags_user_owner": _s(row.owner),
                "resource_tags_user_cost_center": _s(row.cost_center),
                # metadata
                "materialized_at": {"S": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")},
                "schema_version": {"S": "1.0.0"},
                "ttl_expiry": {"N": str(ttl)},
            }
            items.append(item)
    return items


def write_outputs(env: str, items: list[dict]) -> None:
    table = f"finops-feature-store-{env}"

    # 1. create-table CLI
    (OUT / "create_table.sh").write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
aws dynamodb create-table \\
  --table-name {table} \\
  --attribute-definitions AttributeName=resource_id,AttributeType=S AttributeName=date,AttributeType=S \\
  --key-schema AttributeName=resource_id,KeyType=HASH AttributeName=date,KeyType=RANGE \\
  --billing-mode PAY_PER_REQUEST \\
  --region ap-southeast-1
aws dynamodb update-time-to-live \\
  --table-name {table} \\
  --time-to-live-specification "Enabled=true,AttributeName=ttl_expiry" \\
  --region ap-southeast-1
""", encoding="utf-8")

    # 2. batch-write seed (DynamoDB batch-write-item caps at 25 items/request → chunk)
    chunks = [items[i:i + 25] for i in range(0, len(items), 25)]
    seed = {f"{table}__chunk_{i}": [{"PutRequest": {"Item": it}} for it in ch]
            for i, ch in enumerate(chunks)}
    (OUT / "feature_store_seed.json").write_text(json.dumps(seed, indent=2), encoding="utf-8")

    load = "#!/usr/bin/env bash\nset -euo pipefail\n"
    for i in range(len(chunks)):
        # one request-item file per chunk
        reqfile = OUT / f"_req_chunk_{i}.json"
        reqfile.write_text(json.dumps({table: seed[f"{table}__chunk_{i}"]}, indent=2), encoding="utf-8")
        load += f'aws dynamodb batch-write-item --request-items file://{reqfile.name} --region ap-southeast-1\n'
    (OUT / "load_seed.sh").write_text(load, encoding="utf-8")

    # 3. readable markdown sample (decode attribute-values)
    def val(av):
        if "NULL" in av: return "null"
        if "BOOL" in av: return str(av["BOOL"]).lower()
        return list(av.values())[0]
    cols = ["date", "line_item_unblended_cost", "rolling_avg", "cost_ratio_to_7d_avg",
            "robust_z_note", "cpu_mean", "usage_density_24h", "resource_tags_user_owner"]
    lines = [f"### `{table}` — concrete sample items\n",
             "| resource_id (PK) | date (SK) | cost | rolling_avg | cost_ratio_7d | slope_14d | cpu_mean | usage_density | owner_tag |",
             "|---|---|---|---|---|---|---|---|---|"]
    for it in items:
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            val(it["resource_id"]).split(":")[-1], val(it["date"]),
            val(it["line_item_unblended_cost"]), val(it["rolling_avg"]),
            val(it["cost_ratio_to_7d_avg"]), val(it["slope_14d"]),
            val(it["cpu_mean"]), val(it["usage_density_24h"]),
            val(it["resource_tags_user_owner"])))
    (OUT / "feature_store_sample.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="dev")
    args = ap.parse_args()
    items = build_items(args.env)
    write_outputs(args.env, items)
    print(f"Materialized {len(items)} concrete items for finops-feature-store-{args.env}")
    print(f"  data source: {DATA}")
    print(f"  outputs in : {OUT}")
    for f in ["create_table.sh", "feature_store_seed.json", "load_seed.sh", "feature_store_sample.md"]:
        print(f"    - {f}")
    # echo one full item so the CDO sees the exact shape
    print("\n--- one concrete item (DynamoDB JSON) ---")
    mid = min(7, len(items) - 1)
    print(json.dumps(items[mid], indent=2))


if __name__ == "__main__":
    main()
