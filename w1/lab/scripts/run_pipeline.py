from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

try:
    from drain3 import TemplateMiner
    from drain3.template_miner_config import TemplateMinerConfig
except ImportError:  # Drain3 is optional so the pipeline remains runnable in a clean lab env.
    TemplateMiner = None
    TemplateMinerConfig = None


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(r"D:\AWS\AIOPS-study\g2-data\g2")
METRICS_DIR = DATA_DIR / "metrics"
LOGS_DIR = DATA_DIR / "logs"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
ALERT_TIME = pd.Timestamp("2026-06-01T23:04:00Z")
SILENT_SIGNAL_TIME = pd.Timestamp("2026-06-01T15:00:00Z")
EARLIEST_LOG_SIGNAL_TIME = pd.Timestamp("2026-06-01T06:30:19Z")
CART_FEATURES = [
    "memory_usage_bytes",
    "jvm_gc_pause_ms_avg",
    "http_p99_latency_ms",
    "http_5xx_rate",
]


def load_metrics(name: str) -> pd.DataFrame:
    return pd.read_csv(METRICS_DIR / name, parse_dates=["timestamp"])


def isoformat(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def minutes_before_alert(value) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int((ALERT_TIME - pd.Timestamp(value)).total_seconds() // 60)


def format_duration(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins:02d}m"


def first_alarm_time(flags: pd.Series, timestamps: pd.Series, points_required: int = 3, window_points: int = 10):
    """Return first timestamp where at least N anomaly points appear in a 5m/10-point window."""
    alarm = flags.astype(int).rolling(window_points, min_periods=window_points).sum() >= points_required
    matches = timestamps.loc[alarm]
    return matches.min() if not matches.empty else None


def cusum_detection(
    cart: pd.DataFrame,
    metric: str = "memory_usage_bytes",
    baseline_points: int = 720,
    k: float = 0.5,
    h: float = 5.0,
    smoothing_points: int = 1,
) -> dict:
    """Run one-sided CUSUM for sustained upward drift on a single metric."""
    series = cart[metric].rolling(smoothing_points, min_periods=smoothing_points).mean()
    baseline = series.iloc[:baseline_points]
    mu = baseline.mean()
    sigma = baseline.std()
    sigma = sigma if sigma and not pd.isna(sigma) else 1.0
    z = (series - mu) / sigma

    s_pos = []
    running = 0.0
    for value in z.fillna(0.0):
        running = max(0.0, running + value - k)
        s_pos.append(running)
    cart[f"{metric}_cusum_pos"] = s_pos
    cart[f"{metric}_cusum_flag"] = cart[f"{metric}_cusum_pos"] > h

    eligible = cart.index >= baseline_points
    first_raw = cart.loc[eligible & cart[f"{metric}_cusum_flag"], "timestamp"].min()
    alarm_time = first_alarm_time(cart.loc[eligible, f"{metric}_cusum_flag"], cart.loc[eligible, "timestamp"])
    before_silent = cart["timestamp"] < SILENT_SIGNAL_TIME
    before_log_signal = cart["timestamp"] < EARLIEST_LOG_SIGNAL_TIME

    return {
        "method": f"CUSUM ({metric})",
        "metric": metric,
        "baseline_mean": float(mu),
        "baseline_std": float(sigma),
        "first_anomaly": isoformat(first_raw),
        "alarm_5m_3points": isoformat(alarm_time),
        "points_flagged": int(cart[f"{metric}_cusum_flag"].sum()),
        "false_positive_points_before_15_00": int(cart.loc[before_silent, f"{metric}_cusum_flag"].sum()),
        "false_positive_points_before_06_30": int(cart.loc[before_log_signal, f"{metric}_cusum_flag"].sum()),
        "minutes_before_alert": minutes_before_alert(alarm_time),
        "lead_time_before_alert": format_duration(minutes_before_alert(alarm_time)),
        "max_cusum": float(cart[f"{metric}_cusum_pos"].max()),
        "smoothing_points": smoothing_points,
    }


def rolling_zscore_detection(cart: pd.DataFrame, window: int = 60, threshold: float = 3.0) -> tuple[pd.DataFrame, dict]:
    """Run per-metric rolling Z-score with a previous-window baseline."""
    results = []
    combined = pd.Series(False, index=cart.index)
    before_silent = cart["timestamp"] < SILENT_SIGNAL_TIME

    for col in CART_FEATURES:
        mean = cart[col].rolling(window=window, min_periods=window).mean().shift(1)
        std = cart[col].rolling(window=window, min_periods=window).std().shift(1).replace(0, np.nan)
        z = (cart[col] - mean) / std
        flag_col = f"{col}_rolling_z_anomaly"
        z_col = f"{col}_rolling_z"
        cart[z_col] = z
        cart[flag_col] = z.abs() > threshold
        combined |= cart[flag_col].fillna(False)
        first = cart.loc[cart[flag_col], "timestamp"].min()
        results.append(
            {
                "metric": col,
                "first_anomaly": isoformat(first),
                "points_flagged": int(cart[flag_col].sum()),
                "percent_flagged": round(float(cart[flag_col].mean() * 100), 2),
                "false_positive_points_before_15_00": int(cart.loc[before_silent, flag_col].sum()),
            }
        )

    cart["rolling_z_any_anomaly"] = combined
    alarm_time = first_alarm_time(cart["rolling_z_any_anomaly"], cart["timestamp"])
    summary = {
        "method": "Rolling Z-score",
        "first_anomaly": isoformat(cart.loc[combined, "timestamp"].min()),
        "alarm_5m_3points": isoformat(alarm_time),
        "points_flagged": int(combined.sum()),
        "false_positive_points_before_15_00": int(combined.loc[before_silent].sum()),
        "minutes_before_alert": minutes_before_alert(alarm_time),
        "lead_time_before_alert": format_duration(minutes_before_alert(alarm_time)),
    }
    return pd.DataFrame(results), summary


def ewma_detection(cart: pd.DataFrame, window: int = 60, threshold: float = 3.0) -> tuple[pd.DataFrame, dict]:
    """Run EWMA-based deviation detection for smoother baseline tracking."""
    results = []
    combined = pd.Series(False, index=cart.index)
    before_silent = cart["timestamp"] < SILENT_SIGNAL_TIME

    for col in CART_FEATURES:
        ewma_mean = cart[col].ewm(span=window, adjust=False).mean().shift(1)
        ewma_std = cart[col].ewm(span=window, adjust=False).std().shift(1).replace(0, np.nan)
        score = (cart[col] - ewma_mean) / ewma_std
        flag_col = f"{col}_ewma_anomaly"
        score_col = f"{col}_ewma_score"
        cart[score_col] = score
        cart[flag_col] = score.abs() > threshold
        combined |= cart[flag_col].fillna(False)
        first = cart.loc[cart[flag_col], "timestamp"].min()
        results.append(
            {
                "metric": col,
                "first_anomaly": isoformat(first),
                "points_flagged": int(cart[flag_col].sum()),
                "percent_flagged": round(float(cart[flag_col].mean() * 100), 2),
                "false_positive_points_before_15_00": int(cart.loc[before_silent, flag_col].sum()),
            }
        )

    cart["ewma_any_anomaly"] = combined
    alarm_time = first_alarm_time(cart["ewma_any_anomaly"], cart["timestamp"])
    summary = {
        "method": "EWMA",
        "first_anomaly": isoformat(cart.loc[combined, "timestamp"].min()),
        "alarm_5m_3points": isoformat(alarm_time),
        "points_flagged": int(combined.sum()),
        "false_positive_points_before_15_00": int(combined.loc[before_silent].sum()),
        "minutes_before_alert": minutes_before_alert(alarm_time),
        "lead_time_before_alert": format_duration(minutes_before_alert(alarm_time)),
    }
    return pd.DataFrame(results), summary


def isolation_forest_detection(cart: pd.DataFrame) -> dict:
    """Run multivariate Isolation Forest on cart-service metrics."""
    scaler = StandardScaler()
    X = scaler.fit_transform(cart[CART_FEATURES].ffill().fillna(0))
    model = IsolationForest(contamination=0.05, random_state=42, n_estimators=200)
    model.fit(X[:1440])
    cart["if_score"] = -model.decision_function(X)
    cart["if_label"] = model.predict(X)
    cart["if_anomaly"] = cart["if_label"] == -1
    before_silent = cart["timestamp"] < SILENT_SIGNAL_TIME
    alarm_time = first_alarm_time(cart["if_anomaly"], cart["timestamp"])
    alert_score = cart.loc[cart["timestamp"] == ALERT_TIME, "if_score"]
    return {
        "method": "Isolation Forest",
        "first_anomaly": isoformat(cart.loc[cart["if_anomaly"], "timestamp"].min()),
        "alarm_5m_3points": isoformat(alarm_time),
        "points_flagged": int(cart["if_anomaly"].sum()),
        "false_positive_points_before_15_00": int(cart.loc[before_silent, "if_anomaly"].sum()),
        "minutes_before_alert": minutes_before_alert(alarm_time),
        "lead_time_before_alert": format_duration(minutes_before_alert(alarm_time)),
        "alert_time_score": float(alert_score.iloc[0]) if not alert_score.empty else None,
        "top_5_scores": cart.nlargest(5, "if_score")[["timestamp", "if_score"]].assign(
            timestamp=lambda df: df["timestamp"].map(isoformat)
        ).to_dict(orient="records"),
    }


def analyze_cart_metrics(cart: pd.DataFrame) -> dict:
    base = cart.iloc[:720]

    result = {}
    for col in ["memory_usage_bytes", "jvm_gc_pause_ms_avg", "http_p99_latency_ms", "http_5xx_rate", "container_restart_count"]:
        mu = base[col].mean()
        sigma = base[col].std()
        z = (cart[col] - mu) / sigma
        result[f"{col}_first_z_gt_3"] = cart.loc[z > 3, "timestamp"].min()

    mem_mu = base["memory_usage_bytes"].mean()
    mem_sigma = base["memory_usage_bytes"].std()
    cart["memory_z"] = (cart["memory_usage_bytes"] - mem_mu) / mem_sigma
    run = 0
    sustained_memory = None
    for ts, value in zip(cart["timestamp"], cart["memory_z"]):
        if value > 2.5:
            run += 1
            if run >= 6:
                sustained_memory = ts
                break
        else:
            run = 0
    result["sustained_memory_anomaly"] = sustained_memory

    gc_mu = base["jvm_gc_pause_ms_avg"].mean()
    gc_sigma = base["jvm_gc_pause_ms_avg"].std()
    cart["gc_ma_6"] = cart["jvm_gc_pause_ms_avg"].rolling(6, min_periods=6).mean()
    gc_thr = gc_mu + 2 * gc_sigma
    run = 0
    sustained_gc = None
    for ts, value in zip(cart["timestamp"], cart["gc_ma_6"]):
        if pd.notna(value) and value > gc_thr:
            run += 1
            if run >= 6:
                sustained_gc = ts
                break
        else:
            run = 0
    result["sustained_gc_anomaly"] = sustained_gc

    memory_limit = cart["memory_limit_bytes"].replace(0, np.nan)
    cart["memory_utilization_pct"] = cart["memory_usage_bytes"] / memory_limit * 100
    result["memory_first_over_60pct_limit"] = cart.loc[cart["memory_utilization_pct"] > 60, "timestamp"].min()
    result["cart_5xx_first_over_5pct"] = cart.loc[cart["http_5xx_rate"] > 5, "timestamp"].min()
    restart_events = cart.loc[cart["container_restart_count"].diff().fillna(0) > 0, ["timestamp", "container_restart_count"]]
    result["restart_events"] = restart_events.assign(timestamp=lambda df: df["timestamp"].map(isoformat)).to_dict(orient="records")

    cusum_memory_summary = cusum_detection(cart, "memory_usage_bytes", h=12.0, smoothing_points=120)
    cusum_gc_summary = cusum_detection(cart, "jvm_gc_pause_ms_avg", h=10.0, smoothing_points=12)
    zscore_results, zscore_summary = rolling_zscore_detection(cart)
    ewma_results, ewma_summary = ewma_detection(cart)
    iforest_summary = isolation_forest_detection(cart)
    comparison_records = [cusum_memory_summary, cusum_gc_summary, ewma_summary, zscore_summary, iforest_summary]
    comparison = pd.DataFrame(comparison_records)
    zscore_results.to_csv(ARTIFACTS_DIR / "rolling_zscore_results.csv", index=False)
    ewma_results.to_csv(ARTIFACTS_DIR / "ewma_results.csv", index=False)
    comparison.to_csv(ARTIFACTS_DIR / "anomaly_method_comparison.csv", index=False)
    result["rolling_zscore_by_metric"] = zscore_results.to_dict(orient="records")
    result["ewma_by_metric"] = ewma_results.to_dict(orient="records")
    result["recommended_primary_method"] = "CUSUM (memory_usage_bytes)"
    result["recommended_secondary_method"] = "Isolation Forest"
    result["recommended_baseline_method"] = "EWMA"
    result["anomaly_method_comparison"] = comparison_records
    result["ttd_from_earliest_log_signal_minutes"] = minutes_before_alert(EARLIEST_LOG_SIGNAL_TIME)
    result["ttd_from_earliest_log_signal"] = format_duration(minutes_before_alert(EARLIEST_LOG_SIGNAL_TIME))
    result["ttd_from_first_silent_signal_minutes"] = minutes_before_alert(SILENT_SIGNAL_TIME)
    result["ttd_from_first_silent_signal"] = format_duration(minutes_before_alert(SILENT_SIGNAL_TIME))
    result["ttd_from_sustained_memory_minutes"] = minutes_before_alert(sustained_memory)
    result["ttd_from_sustained_memory"] = format_duration(minutes_before_alert(sustained_memory))
    return result


def analyze_service_metrics(name: str, df: pd.DataFrame, col: str) -> dict:
    base = df.iloc[:720]
    mu, sigma = base[col].mean(), base[col].std()
    z = (df[col] - mu) / sigma
    return {
        "first_z_gt_3": df.loc[z > 3, "timestamp"].min(),
        "baseline_mean": float(mu),
        "baseline_std": float(sigma),
    }


def normalize_message(msg: str) -> str:
    msg = re.sub(r"\b[0-9a-f]{16,}\b", "<hex>", msg, flags=re.I)
    msg = re.sub(r"\b\d+\.\d+\b", "<num>", msg)
    msg = re.sub(r"\b\d+\b", "<num>", msg)
    msg = re.sub(r"\bORD-[A-Z0-9]+\b", "ORD-<id>", msg)
    msg = re.sub(r"userId=<num>", "userId=<id>", msg)
    return msg


def analyze_logs(name: str) -> dict:
    path = LOGS_DIR / name
    template_counts = Counter()
    first_seen = {}
    last_seen = {}
    levels = Counter()
    samples = {}
    trace_counts = Counter()
    trace_level_counts = Counter()
    template_miner = None
    if TemplateMiner is not None:
        config = TemplateMinerConfig()
        config.load_default_config()
        config.profiling_enabled = False
        template_miner = TemplateMiner(config=config)

    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            levels[rec["level"]] += 1
            if rec.get("trace_id"):
                trace_counts[rec["trace_id"]] += 1
                trace_level_counts[(rec["trace_id"], rec["level"])] += 1
            if template_miner is not None:
                drain_result = template_miner.add_log_message(rec["message"])
                template = drain_result["template_mined"]
            else:
                template = normalize_message(rec["message"])
            template_counts[template] += 1
            first_seen.setdefault(template, rec["timestamp"])
            last_seen[template] = rec["timestamp"]
            samples.setdefault(template, rec["message"])
    rows = []
    for template, count in template_counts.most_common():
        rows.append(
            {
                "template": template,
                "count": count,
                "first_seen": first_seen[template],
                "last_seen": last_seen[template],
                "sample": samples[template],
            }
        )
    pd.DataFrame(rows).to_csv(ARTIFACTS_DIR / f"{name}.templates.csv", index=False)
    pd.DataFrame(rows[:20]).to_csv(ARTIFACTS_DIR / f"{name}.templates_top20.csv", index=False)
    trace_rows = [
        {"trace_id": tid, "count": count}
        for tid, count in trace_counts.most_common(20)
    ]
    pd.DataFrame(trace_rows).to_csv(ARTIFACTS_DIR / f"{name}.trace_top20.csv", index=False)
    key_events = {}
    for label in [
        "ProductCatalogCache eviction failed",
        "GC overhead limit warning",
        "OutOfMemoryError imminent",
        "Container OOMKilled",
        "Application starting up",
        "Connection pool nearing limit",
        "Upstream connection refused",
    ]:
        match = next((row for row in rows if label in row["template"]), None)
        if match:
            key_events[label] = {
                "first_seen": match["first_seen"],
                "last_seen": match["last_seen"],
                "count": match["count"],
                "template": match["template"],
            }

    return {
        "parser": "Drain3" if template_miner is not None else "regex-normalization-fallback",
        "levels": dict(levels),
        "templates_top20": rows[:20],
        "key_events": key_events,
        "trace_top20": trace_rows,
    }


def main() -> None:
    cart = load_metrics("cart-service.csv")
    api = load_metrics("api-gateway.csv")
    order = load_metrics("order-service.csv")
    payment = load_metrics("payment-service.csv")
    product = load_metrics("product-service.csv")

    cart_analysis = analyze_cart_metrics(cart)
    api_analysis = analyze_service_metrics("api-gateway", api, "cart_upstream_error_rate")
    order_analysis = analyze_service_metrics("order-service", order, "upstream_timeout_rate")
    payment_analysis = analyze_service_metrics("payment-service", payment, "upstream_timeout_rate")
    product_analysis = analyze_service_metrics("product-service", product, "http_5xx_rate")

    cart_logs = analyze_logs("cart-service.log.jsonl")
    order_logs = analyze_logs("order-service.log.jsonl")

    report = {
        "cart_metrics": cart_analysis,
        "api_metrics": api_analysis,
        "order_metrics": order_analysis,
        "payment_metrics": payment_analysis,
        "product_metrics": product_analysis,
        "cart_logs": cart_logs,
        "order_logs": order_logs,
        "when_file": "cart-service.csv",
        "where_files": ["cart-service.csv", "cart-service.log.jsonl", "api-gateway.csv", "order-service.csv", "order-service.log.jsonl"],
        "what_files": ["cart-service.csv", "cart-service.log.jsonl", "api-gateway.csv", "order-service.csv", "payment-service.csv"],
    }
    (ARTIFACTS_DIR / "analysis_summary.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
