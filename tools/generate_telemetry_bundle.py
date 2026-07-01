#!/usr/bin/env python3
"""
Generate production-grade telemetry bundles from TF2 finops CSV dataset.
Outputs contract-aligned JSON batches ready for POST /v1/detect validation.

Run: python AIO2/tools/generate_telemetry_bundle.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "capstone-phase2" / "data" / "tf2-finops"
OUT = DATA / "generated"
RNG = np.random.default_rng(42)

ENVIRONMENTS = [
    "prod", "prod-core", "prod-payments", "staging", "dev",
    "sandbox", "ml-research", "data-analytics",
]


def load_cur() -> pd.DataFrame:
    cur = pd.read_csv(DATA / "cur_line_items.csv", parse_dates=["line_item_usage_start_date"])
    cur["date"] = cur["line_item_usage_start_date"].dt.date.astype(str)
    cur["line_item_usage_account_id"] = cur["line_item_usage_account_id"].astype(str)
    return cur


def load_ce() -> pd.DataFrame:
    ce = pd.read_csv(DATA / "cost_explorer_daily.csv", parse_dates=["date"])
    ce["linked_account_id"] = ce["linked_account_id"].astype(str)
    return ce


def compute_usage_density(cur: pd.DataFrame) -> pd.DataFrame:
    """usage_density_24h = usage_hours/24 for Hrs pricing unit."""
    df = cur.copy()
    df["usage_density_24h"] = np.where(
        df["pricing_unit"] == "Hrs",
        (df["line_item_usage_amount"] / 24.0).clip(0, 1),
        np.nan,
    )
    return df


def generate_traffic(daily_cost: pd.DataFrame) -> pd.DataFrame:
    traffic_path = DATA / "synthetic_traffic_daily.csv"
    if traffic_path.exists():
        t = pd.read_csv(traffic_path)
        t["date"] = pd.to_datetime(t["date"]).dt.date.astype(str)
        return t
    # inline fallback
    daily = daily_cost.copy()
    daily["traffic_volume"] = (daily["daily_cost"] * 120).astype(int).clip(100)
    daily["traffic_source"] = "Synthetic"
    return daily


def synthetic_cloudwatch(resource_ids: list[str], date: str, cost: float) -> list[dict]:
    """Generate plausible CloudWatch metrics correlated with cost."""
    metrics = []
    for rid in resource_ids[:50]:  # cap per batch sample
        base_cpu = float(RNG.uniform(5, 95))
        if cost < 10:
            base_cpu = float(RNG.uniform(0, 8))  # idle pattern
        hourly = [round(max(0, min(100, base_cpu + RNG.normal(0, 3))), 1) for _ in range(24)]
        metrics.append({
            "resource_id": rid,
            "cpu_percent": round(float(np.mean(hourly)), 2),
            "cpu_utilization_hourly": hourly,
            "memory_mib": round(float(RNG.uniform(512, 65536)), 0) if "ec2" in rid.lower() or rid.startswith("i-") else None,
            "network_in_bytes": int(RNG.integers(1_000_000, 50_000_000)),
            "network_out_bytes": int(RNG.integers(1_000_000, 80_000_000)),
            "disk_io_ops": int(RNG.integers(0, 5000)),
            "database_connections": int(RNG.integers(0, 200)) if "rds" in rid.lower() else None,
            "gpu_utilization": round(float(RNG.uniform(50, 99)), 1) if "p3" in rid or "ml" in rid.lower() else None,
        })
    return metrics


def cur_row_to_signal(row: pd.Series) -> dict:
    env = row.get("resource_tags_user_environment")
    if pd.isna(env) or env == "":
        env = "dev"
    out = {
        "bill_billing_period_start_date": str(row.get("bill_billing_period_start_date", "")),
        "bill_payer_account_id": str(row.get("bill_payer_account_id", "100000000001")),
        "line_item_usage_start_date": row["line_item_usage_start_date"].isoformat().replace("+00:00", "Z")
        if hasattr(row["line_item_usage_start_date"], "isoformat")
        else str(row["line_item_usage_start_date"]),
        "line_item_usage_end_date": str(row.get("line_item_usage_end_date", "")),
        "line_item_usage_account_id": str(row["line_item_usage_account_id"]),
        "line_item_usage_account_name": str(row.get("line_item_usage_account_name", "")),
        "line_item_line_item_type": str(row.get("line_item_line_item_type", "Usage")),
        "line_item_product_code": str(row["line_item_product_code"]),
        "line_item_usage_type": str(row["line_item_usage_type"]),
        "line_item_operation": str(row.get("line_item_operation", "")),
        "line_item_resource_id": None if pd.isna(row.get("line_item_resource_id")) else str(row["line_item_resource_id"]),
        "line_item_usage_amount": float(row["line_item_usage_amount"]),
        "pricing_unit": str(row["pricing_unit"]),
        "line_item_unblended_rate": float(row.get("line_item_unblended_rate", 0)),
        "line_item_unblended_cost": float(row["line_item_unblended_cost"]),
        "line_item_currency_code": str(row.get("line_item_currency_code", "USD")),
        "product_product_name": str(row.get("product_product_name", "")),
        "product_region_code": None if pd.isna(row.get("product_region_code")) else str(row["product_region_code"]),
        "product_instance_type": None if pd.isna(row.get("product_instance_type")) else str(row["product_instance_type"]),
        "resource_tags_user_environment": env,
        "resource_tags_user_team": None if pd.isna(row.get("resource_tags_user_team")) else str(row["resource_tags_user_team"]),
        "resource_tags_user_owner": None if pd.isna(row.get("resource_tags_user_owner")) else str(row["resource_tags_user_owner"]),
        "resource_tags_user_cost_center": None if pd.isna(row.get("resource_tags_user_cost_center")) else str(row["resource_tags_user_cost_center"]),
    }
    if not pd.isna(row.get("usage_density_24h")):
        out["usage_density_24h"] = round(float(row["usage_density_24h"]), 4)
    return out


def ce_row_to_signal(row: pd.Series) -> dict:
    return {
        "date": str(row["date"].date()) if hasattr(row["date"], "date") else str(row["date"])[:10],
        "linked_account_id": str(row["linked_account_id"]),
        "linked_account_name": str(row["linked_account_name"]),
        "service": str(row["service"]),
        "service_code": str(row["service_code"]),
        "region": None if pd.isna(row.get("region")) else str(row["region"]),
        "unblended_cost": round(float(row["unblended_cost"]), 4),
        "is_estimated": bool(row["is_estimated"]) if isinstance(row["is_estimated"], bool) else str(row["is_estimated"]).lower() == "true",
    }


def build_feature_store_row(
    resource_id: str,
    date: str,
    cost: float,
    usage_amount: float,
    density: float | None,
    traffic: float,
) -> dict:
    cpr = cost / max(traffic, 1)
    return {
        "resource_id": resource_id,
        "date": date,
        "unblended_cost": round(cost, 4),
        "usage_amount": round(usage_amount, 4),
        "usage_density_24h": round(density, 4) if density is not None else None,
        "traffic_volume": int(traffic),
        "cost_per_request": round(cpr, 8),
        "cpu_percent": round(float(RNG.uniform(2, 95)), 2),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cur = compute_usage_density(load_cur())
    ce = load_ce()

    daily_cost = (
        cur.groupby(["date", "line_item_usage_account_id", "line_item_usage_account_name"], as_index=False)
        .agg(daily_cost=("line_item_unblended_cost", "sum"))
    )
    daily_cost["line_item_usage_account_id"] = daily_cost["line_item_usage_account_id"].astype(str)
    traffic = generate_traffic(daily_cost)
    if "linked_account_id" in traffic.columns:
        traffic["linked_account_id"] = traffic["linked_account_id"].astype(str)
    daily = daily_cost.merge(
        traffic[["date", "linked_account_id", "traffic_volume", "traffic_source"]],
        left_on=["date", "line_item_usage_account_id"],
        right_on=["date", "linked_account_id"],
        how="left",
    )
    daily["traffic_volume"] = daily["traffic_volume"].fillna(100).astype(int)
    daily["traffic_source"] = daily["traffic_source"].fillna("Synthetic")
    daily["cost_per_request"] = daily["daily_cost"] / daily["traffic_volume"].clip(lower=1)

  # --- Enriched CSV exports ---
    daily.to_csv(OUT / "daily_cost_with_traffic.csv", index=False)

    feature_rows = []
    for (date, acct), grp in cur.groupby(["date", "line_item_usage_account_id"]):
        tr = daily[(daily["date"] == date) & (daily["line_item_usage_account_id"] == acct)]
        tv = float(tr["traffic_volume"].iloc[0]) if len(tr) else 100.0
        for _, row in grp.iterrows():
            rid = row.get("line_item_resource_id")
            if pd.isna(rid):
                continue
            feature_rows.append(
                build_feature_store_row(
                    str(rid), date, float(row["line_item_unblended_cost"]),
                    float(row["line_item_usage_amount"]),
                    None if pd.isna(row.get("usage_density_24h")) else float(row["usage_density_24h"]),
                    tv,
                )
            )
    pd.DataFrame(feature_rows).to_csv(OUT / "feature_store_daily.csv", index=False)

    # CE 30-day windows per account (sample last date)
    sample_date = "2026-05-31"
    ce_window = ce[ce["date"] >= pd.Timestamp("2026-05-02")].copy()
    ce_signals = [ce_row_to_signal(r) for _, r in ce_window.iterrows()]
    pd.DataFrame(ce_signals).to_csv(OUT / "aws_cost_explorer_daily_30d.csv", index=False)

    # Sample detect batch — prod-core 2026-05-31
    batch_date = sample_date
    acct_id = "200000000010"
    cur_day = cur[(cur["date"] == batch_date) & (cur["line_item_usage_account_id"] == acct_id)]
    cur_signals = [cur_row_to_signal(r) for _, r in cur_day.iterrows()]
    rids = [s["line_item_resource_id"] for s in cur_signals if s["line_item_resource_id"]]
    day_cost = float(cur_day["line_item_unblended_cost"].sum())
    tr_row = daily[(daily["date"] == batch_date) & (daily["line_item_usage_account_id"] == acct_id)].iloc[0]

    detect_request = {
        "data_source_type": "RAW_JSON",
        "is_ad_hoc": False,
        "telemetry_delay_event": False,
        "business_context": {
            "linked_account_id": acct_id,
            "traffic_volume": int(tr_row["traffic_volume"]),
            "traffic_source": str(tr_row["traffic_source"]),
            "campaign_flag": False,
            "load_test_flag": False,
            "migration_flag": False,
        },
        "aws_cur_line_items": cur_signals,
        "resource_utilization_metrics": synthetic_cloudwatch(rids, batch_date, day_cost),
    }

    metrics_summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_versions": {
            "ai_api_contract": "v1.4.0",
            "telemetry_contract": "v3.2.0",
            "deployment_contract": "v1.3.0",
        },
        "dataset": {
            "cur_line_items": len(cur),
            "ce_daily_rows": len(ce),
            "date_range": [str(cur["date"].min()), str(cur["date"].max())],
            "accounts": int(cur["line_item_usage_account_id"].nunique()),
            "resources": int(cur["line_item_resource_id"].nunique()),
        },
        "generated_files": [
            "daily_cost_with_traffic.csv",
            "feature_store_daily.csv",
            "aws_cost_explorer_daily_30d.csv",
            "sample_detect_request_2026-05-31_prod-core.json",
            "metrics_summary.json",
        ],
        "feature_engineering": {
            "cost_per_request_formula": "daily_cost / max(traffic_volume, 1)",
            "usage_density_24h_formula": "line_item_usage_amount / 24 (when pricing_unit=Hrs)",
            "traffic_source": "Synthetic (correlated with CE daily cost)",
        },
    }

    with open(OUT / "sample_detect_request_2026-05-31_prod-core.json", "w", encoding="utf-8") as f:
        json.dump(detect_request, f, indent=2, ensure_ascii=False)

    with open(OUT / "metrics_summary.json", "w", encoding="utf-8") as f:
        json.dump(metrics_summary, f, indent=2, ensure_ascii=False)

    print(f"Generated telemetry bundle in {OUT}")
    print(json.dumps(metrics_summary, indent=2))


if __name__ == "__main__":
    main()
