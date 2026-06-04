from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


SECONDS_PER_DAY = 86_400
DAYS_PER_MONTH = 30


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


def monthly_gb_from_logs(log_gb_per_day: float) -> float:
    return log_gb_per_day * DAYS_PER_MONTH


def monthly_metric_samples(metric_events_per_sec: int) -> float:
    return metric_events_per_sec * SECONDS_PER_DAY * DAYS_PER_MONTH


def build_cost(tier: Tier) -> dict[str, float]:
    log_gb_month = monthly_gb_from_logs(tier.log_gb_per_day)
    metric_samples_month = monthly_metric_samples(tier.metric_events_per_sec)

    log_hot_gb = log_gb_month * 0.2
    log_cold_gb = log_gb_month * 0.8
    metric_bytes_gb = metric_samples_month * 120 / 1_000_000_000

    storage = (
        log_hot_gb * 0.12
        + log_cold_gb * 0.023
        + metric_bytes_gb * 0.04
    )

    collector_compute = tier.services * 18
    kafka_compute = max(2, tier.services // 20) * 65
    stream_compute = (tier.metric_events_per_sec / 100_000) * 88
    compute = collector_compute + kafka_compute + stream_compute

    network = log_gb_month * 0.05 + metric_samples_month * 120 / 1_000_000_000 * 0.02

    return {"storage": storage, "compute": compute, "network": network}


def datadog_cost(tier: Tier) -> dict[str, float]:
    log_gb_month = monthly_gb_from_logs(tier.log_gb_per_day)
    metric_samples_month = monthly_metric_samples(tier.metric_events_per_sec)

    log_indexed_gb = log_gb_month * 0.3
    log_archived_gb = log_gb_month * 0.7
    metric_cost_units = (tier.metric_events_per_sec / 100_000) * DAYS_PER_MONTH

    storage = (
        log_indexed_gb * 0.75
        + log_archived_gb * 0.15
        + metric_cost_units * 5.0
    )

    infra_host = tier.services * 27
    custom_metrics = max(1, tier.metric_events_per_sec // 100_000) * 5
    compute = infra_host + custom_metrics

    network = log_gb_month * 0.08 + metric_samples_month * 120 / 1_000_000_000 * 0.03

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
