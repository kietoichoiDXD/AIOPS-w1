from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd


@dataclass
class Tier:
    name: str
    services: int
    log_gb_per_day: float
    metric_events_per_sec: int


TIERS = [
    Tier("Small", 10, 50, 100_000),
    Tier("Medium", 100, 500, 1_000_000),
    Tier("Large", 1000, 5000, 10_000_000),
]


def estimate_build_cost(tier: Tier) -> Dict[str, float]:
    monthly_log_gb = tier.log_gb_per_day * 30
    metric_gb_month = tier.metric_events_per_sec * 0.000004 * 30
    storage = monthly_log_gb * 0.023 + metric_gb_month * 0.20
    compute = tier.services * 55 + (tier.metric_events_per_sec / 100_000) * 120
    network = monthly_log_gb * 0.09
    return {"storage": storage, "compute": compute, "network": network}


def estimate_datadog_cost(tier: Tier) -> Dict[str, float]:
    monthly_log_gb = tier.log_gb_per_day * 30
    metric_events_m = tier.metric_events_per_sec * 30 * 24 * 3600 / 1_000_000
    storage = monthly_log_gb * 0.50 + metric_events_m * 0.15
    compute = tier.services * 150
    network = monthly_log_gb * 0.15
    return {"storage": storage, "compute": compute, "network": network}


def format_table(tier: Tier) -> pd.DataFrame:
    build = estimate_build_cost(tier)
    buy = estimate_datadog_cost(tier)
    rows = [
        {
            "tier": tier.name,
            "option": "Build",
            **build,
            "total": sum(build.values()),
        },
        {
            "tier": tier.name,
            "option": "Datadog",
            **buy,
            "total": sum(buy.values()),
        },
    ]
    return pd.DataFrame(rows)


def main() -> None:
    frames = [format_table(tier) for tier in TIERS]
    result = pd.concat(frames, ignore_index=True)
    result[["storage", "compute", "network", "total"]] = result[
        ["storage", "compute", "network", "total"]
    ].round(2)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
