from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(r"D:\AWS\AIOPS-study\g2-data\g2")
METRICS_DIR = DATA_DIR / "metrics"
LOGS_DIR = DATA_DIR / "logs"
ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def load_metrics(name: str) -> pd.DataFrame:
    return pd.read_csv(METRICS_DIR / name, parse_dates=["timestamp"])


def analyze_cart_metrics(cart: pd.DataFrame) -> dict:
    base = cart.iloc[:720]
    features = [
        "memory_usage_bytes",
        "cpu_usage_percent",
        "http_requests_per_sec",
        "http_p99_latency_ms",
        "http_5xx_rate",
        "jvm_gc_pause_ms_avg",
    ]

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

    scaler = StandardScaler()
    X = scaler.fit_transform(cart[features])
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(X[:1440])
    scores = -model.decision_function(X)
    cart["if_score"] = scores
    cart["if_label"] = model.predict(X)
    result["if_first_anomaly"] = cart.loc[cart["if_label"] == -1, "timestamp"].min()
    result["if_top_5"] = cart.nlargest(5, "if_score")[["timestamp", "if_score"]].to_dict(orient="records")
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
    with path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            levels[rec["level"]] += 1
            if rec.get("trace_id"):
                trace_counts[rec["trace_id"]] += 1
                trace_level_counts[(rec["trace_id"], rec["level"])] += 1
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
    trace_rows = [
        {"trace_id": tid, "count": count}
        for tid, count in trace_counts.most_common(20)
    ]
    pd.DataFrame(trace_rows).to_csv(ARTIFACTS_DIR / f"{name}.trace_top20.csv", index=False)
    return {"levels": dict(levels), "templates": rows, "trace_top20": trace_rows}


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
