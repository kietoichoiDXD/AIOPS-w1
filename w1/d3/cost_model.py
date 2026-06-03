from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
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


def build_cost(tier: Tier) -> dict[str, float]:
    monthly_log_gb = tier.log_gb_per_day * 30
    metric_points_m = tier.metric_events_per_sec * 30 * 24 * 3600 / 1_000_000
    storage = monthly_log_gb * 0.023 + metric_points_m * 0.12
    compute = tier.services * 42 + (tier.metric_events_per_sec / 100_000) * 95
    network = monthly_log_gb * 0.08 + (tier.services * 3)
    return {"storage": storage, "compute": compute, "network": network}


def datadog_cost(tier: Tier) -> dict[str, float]:
    monthly_log_gb = tier.log_gb_per_day * 30
    metric_points_m = tier.metric_events_per_sec * 30 * 24 * 3600 / 1_000_000
    storage = monthly_log_gb * 0.45 + metric_points_m * 0.18
    compute = tier.services * 125
    network = monthly_log_gb * 0.12 + (tier.services * 5)
    return {"storage": storage, "compute": compute, "network": network}


def row_for(tier: Tier, option: str, values: dict[str, float]) -> dict[str, float | str]:
    return {"tier": tier.name, "option": option, **values, "total": sum(values.values())}


def main() -> None:
    rows = []
    for tier in TIERS:
        rows.append(row_for(tier, "Build", build_cost(tier)))
        rows.append(row_for(tier, "Datadog", datadog_cost(tier)))

    result = pd.DataFrame(rows)
    result[["storage", "compute", "network", "total"]] = result[
        ["storage", "compute", "network", "total"]
    ].round(2)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
