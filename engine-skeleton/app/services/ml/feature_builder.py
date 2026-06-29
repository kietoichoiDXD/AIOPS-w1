"""
feature_builder.py — Convert API request payload (CURLineItem + ResourceUtilizationMetric)
into the FEATURE_v2 feature DataFrame used by the XGBoost model.

Mirrors FEATURE_v2.py logic but operates on the API schema types instead of CSV files.
Key invariant: rolling stats use .shift(1) so no current-day look-ahead leaks into features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import linregress
from typing import Sequence

from app.schemas.detect import CURLineItem, ResourceUtilizationMetric


FEATURE_COLS_V2: list[str] = [
    "line_item_unblended_cost", "rolling_7d_avg", "rolling_7d_std",
    "cost_ratio_to_7d_avg", "cost_diff", "robust_z",
    "slope_14d", "cost_pct_change_28d", "age_days",
    "month", "is_weekend",
    "cost_per_unit_usage",
    "cpu_mean", "cpu_std", "cpu_min", "cpu_variance_24h",
    "memory_mib", "network_in_bytes", "network_out_bytes", "disk_io_ops",
    "team_missing", "owner_missing", "peer_ratio",
    "absolute_cost_spike",
    "ddb_flag",
]


def _max_idle_streak(hourly: list[float]) -> int:
    """Max consecutive hours with CPU < 5%."""
    max_s = cur = 0
    for v in hourly:
        if v < 5:
            cur += 1
            max_s = max(max_s, cur)
        else:
            cur = 0
    return max_s


def _slope(s: pd.Series) -> float:
    if len(s) < 14:
        return float("nan")
    x = np.arange(len(s))
    slope, *_ = linregress(x, s.values)
    return float(slope)


def _build_metrics_lookup(
    metrics: Sequence[ResourceUtilizationMetric] | None,
) -> dict[str, dict]:
    """Map resource_id → metric dict for O(1) lookup."""
    if not metrics:
        return {}
    result: dict[str, dict] = {}
    for m in metrics:
        hourly = m.hourly_cpu_percent or []
        cpu_arr = np.array(hourly) if hourly else np.array([m.cpu_percent])
        result[m.resource_id] = {
            "cpu_mean": float(cpu_arr.mean()),
            "cpu_std": float(cpu_arr.std()) if len(cpu_arr) > 1 else 0.0,
            "cpu_min": float(cpu_arr.min()),
            "cpu_variance_24h": float(cpu_arr.var()) if len(cpu_arr) > 1 else 0.0,
            "memory_mib": float(m.memory_mib or 0),
            "network_in_bytes": float(m.network_in_bytes or 0),
            "network_out_bytes": float(m.network_out_bytes or 0),
            "disk_io_ops": float(m.disk_io_ops or 0),
        }
    return result


def build_feature_dataframe(
    cur_items: Sequence[CURLineItem],
    metrics: Sequence[ResourceUtilizationMetric] | None = None,
    train_stats: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Convert CUR line items + utilization metrics into FEATURE_v2 features.

    Returns:
        X  — DataFrame with FEATURE_COLS_V2 columns, one row per CUR item
        df — Full DataFrame (includes metadata columns for result mapping)
    """
    if not cur_items:
        return pd.DataFrame(columns=FEATURE_COLS_V2), pd.DataFrame()

    metrics_lut = _build_metrics_lookup(metrics)

    rows = []
    for item in cur_items:
        m = metrics_lut.get(item.line_item_resource_id, {})
        rows.append({
            "line_item_resource_id": item.line_item_resource_id,
            "line_item_usage_account_id": item.line_item_usage_account_id,
            "line_item_product_code": item.line_item_product_code,
            "clean_date": pd.to_datetime(item.line_item_usage_start_date).normalize(),
            "line_item_unblended_cost": float(item.line_item_unblended_cost),
            "line_item_usage_amount": float(item.line_item_usage_amount),
            "resource_tags_user_team": item.resource_tags_user_team,
            "resource_tags_user_owner": item.resource_tags_user_owner,

            "cpu_mean": m.get("cpu_mean", 0.0),
            "cpu_std": m.get("cpu_std", 0.0),
            "cpu_min": m.get("cpu_min", 0.0),
            "cpu_variance_24h": m.get("cpu_variance_24h", 0.0),
            "memory_mib": m.get("memory_mib", 0.0),
            "network_in_bytes": m.get("network_in_bytes", 0.0),
            "network_out_bytes": m.get("network_out_bytes", 0.0),
            "disk_io_ops": m.get("disk_io_ops", 0.0),

            "resource_tags_user_environment": getattr(item, "resource_tags_user_environment", "dev"),
        })

    df = pd.DataFrame(rows).sort_values(["line_item_resource_id", "clean_date"]).reset_index(drop=True)
    grp = df.groupby("line_item_resource_id")


    df["rolling_7d_avg"] = grp["line_item_unblended_cost"].transform(
        lambda x: x.shift(1).rolling(7, min_periods=1).mean()
    )
    df["rolling_7d_std"] = grp["line_item_unblended_cost"].transform(
        lambda x: x.shift(1).rolling(7, min_periods=2).std()
    ).fillna(0)

    df["cost_ratio_to_7d_avg"] = df["line_item_unblended_cost"] / (df["rolling_7d_avg"] + 1e-6)
    df["cost_diff"] = df["line_item_unblended_cost"] - df["rolling_7d_avg"]

    rolling_median = grp["line_item_unblended_cost"].transform(
        lambda x: x.shift(1).rolling(14, min_periods=3).median()
    )
    rolling_mad = grp["line_item_unblended_cost"].transform(
        lambda x: x.shift(1).rolling(14, min_periods=3).apply(
            lambda y: np.median(np.abs(y - np.median(y))), raw=True
        )
    )
    df["robust_z"] = (
        0.6745 * (df["line_item_unblended_cost"] - rolling_median) / (rolling_mad + 1e-6)
    ).fillna(0)

    df["absolute_cost_spike"] = (
        df["line_item_unblended_cost"] - 3 * df["rolling_7d_std"]
    ).clip(lower=0)

    cost_lag_28d = grp["line_item_unblended_cost"].shift(28)
    df["cost_pct_change_28d"] = (
        (df["line_item_unblended_cost"] - cost_lag_28d) / (cost_lag_28d + 1e-6)
    ).fillna(0)

    df["slope_14d"] = grp["line_item_unblended_cost"].transform(
        lambda x: x.shift(1).rolling(14, min_periods=14).apply(_slope)
    ).fillna(0)


    df["month"] = df["clean_date"].dt.month
    df["is_weekend"] = (df["clean_date"].dt.dayofweek >= 5).astype(int)


    df["cost_per_unit_usage"] = df["line_item_unblended_cost"] / (df["line_item_usage_amount"] + 1e-6)
    df["age_days"] = grp.cumcount() + 1


    df["team_missing"] = df["resource_tags_user_team"].isna().astype(int)
    df["owner_missing"] = df["resource_tags_user_owner"].isna().astype(int)


    peer_key = ["line_item_usage_account_id", "line_item_product_code", "clean_date"]
    df["peer_median_cost"] = df.groupby(peer_key)["line_item_unblended_cost"].transform("median")
    df["peer_ratio"] = df["line_item_unblended_cost"] / (df["peer_median_cost"] + 1e-6)


    df["ddb_flag"] = (df["line_item_product_code"] == "AmazonDynamoDB").astype(int)


    numeric_cols = df.select_dtypes(include="number").columns
    df[numeric_cols] = df[numeric_cols].replace([np.inf, -np.inf], np.nan)

    if train_stats:
        global_med = train_stats.get("global_medians", pd.Series(dtype=float))
        for col in numeric_cols:
            if df[col].isna().any():
                fallback = float(global_med.get(col, 0)) if col in global_med.index else 0.0
                df[col] = df[col].fillna(fallback)
    else:
        df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())


    available_features = [f for f in FEATURE_COLS_V2 if f in df.columns]
    missing_features = [f for f in FEATURE_COLS_V2 if f not in df.columns]
    for f in missing_features:
        df[f] = 0.0

    X = df[FEATURE_COLS_V2].copy()
    return X, df
