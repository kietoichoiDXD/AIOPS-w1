#!/usr/bin/env python3
"""
Generate synthetic traffic_volume for TF2 backtest.
Correlates with daily CE cost per account (benign flash-sale events get proportional traffic bump).

Run: python AIO2/tools/generate_synthetic_traffic.py
Output: capstone-phase2/data/tf2-finops/synthetic_traffic_daily.csv
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "capstone-phase2" / "data" / "tf2-finops"
CE_PATH = DATA / "cost_explorer_daily.csv"
OUT_PATH = DATA / "synthetic_traffic_daily.csv"

# Base requests per USD spend (tunable)
REQUESTS_PER_USD = 120.0
RNG = np.random.default_rng(42)


def main() -> None:
    ce = pd.read_csv(CE_PATH, parse_dates=["date"])
    daily = (
        ce.groupby(["date", "linked_account_id", "linked_account_name"], as_index=False)["unblended_cost"]
        .sum()
        .rename(columns={"unblended_cost": "daily_cost"})
    )

    # Rolling 7d avg per account for spike detection
    daily = daily.sort_values(["linked_account_id", "date"])
    daily["rolling_7d_avg"] = (
        daily.groupby("linked_account_id")["daily_cost"]
        .transform(lambda s: s.rolling(7, min_periods=1).mean())
    )
    daily["cost_ratio"] = daily["daily_cost"] / daily["rolling_7d_avg"].clip(lower=1)

    # Benign surge: traffic scales with cost (flash sale pattern)
    # True anomaly would have high cost_ratio but traffic NOT scaling — injected separately in labels
    base_traffic = daily["daily_cost"] * REQUESTS_PER_USD
    noise = RNG.normal(0, 0.05, len(daily))
    scale = np.where(daily["cost_ratio"] > 1.5, daily["cost_ratio"] * 0.9, 1.0)
    daily["traffic_volume"] = (base_traffic * scale * (1 + noise)).clip(lower=100).astype(int)
    daily["traffic_source"] = "Synthetic"
    daily["date"] = daily["date"].dt.strftime("%Y-%m-%d")

    out = daily[
        ["date", "linked_account_id", "linked_account_name", "daily_cost", "traffic_volume", "traffic_source", "cost_ratio"]
    ]
    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {len(out)} rows → {OUT_PATH}")
    print(out.describe(include="all"))


if __name__ == "__main__":
    main()
