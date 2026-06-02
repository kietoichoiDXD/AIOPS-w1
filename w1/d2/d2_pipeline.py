from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from sklearn.metrics import precision_recall_fscore_support
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import IsolationForest


try:
    from drain3.template_miner import TemplateMiner  # type: ignore
    from drain3.template_miner_config import TemplateMinerConfig  # type: ignore
    DRAIN3_AVAILABLE = True
except Exception:
    TemplateMiner = None  # type: ignore
    TemplateMinerConfig = None  # type: ignore
    DRAIN3_AVAILABLE = False


TOKEN_PATTERNS = [
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"), "<IP>"),
    (re.compile(r"\b\d{1,5}\b"), "<NUM>"),
    (re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE), "<HEX>"),
    (re.compile(r"\b[A-Z]{2,}-\d+\b"), "<ID>"),
]


@dataclass(frozen=True)
class ParsedEntry:
    raw: str
    timestamp: pd.Timestamp | None
    template: str
    template_id: str
    is_new_template: bool = False


def normalize_text(line: str) -> str:
    text = line.strip()
    for pattern, replacement in TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text)
    return text


def infer_timestamp(line: str) -> pd.Timestamp | None:
    patterns = [
        r"^\[(?P<ts>[^\]]+)\]",
        r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, line)
        if m:
            return pd.to_datetime(m.group("ts"), errors="coerce")
    return None


def load_lines(path: Path) -> list[str]:
    return [line.rstrip("\n") for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def build_drain_miner(sim_th: float):
    if not DRAIN3_AVAILABLE:
        return None
    cfg = TemplateMinerConfig()
    cfg.drain_sim_th = sim_th
    cfg.drain_depth = 4
    cfg.drain_max_children = 100
    cfg.drain_max_clusters = 1000
    return TemplateMiner(config=cfg)


def parse_with_drain(lines: Iterable[str], sim_th: float = 0.4) -> tuple[list[ParsedEntry], dict]:
    miner = build_drain_miner(sim_th)
    parsed: list[ParsedEntry] = []
    template_seen: set[str] = set()
    if miner is None:
        for i, line in enumerate(lines):
            template = normalize_text(line)
            tid = f"T{abs(hash(template)) % 100000}"
            is_new = template not in template_seen
            template_seen.add(template)
            parsed.append(ParsedEntry(line, infer_timestamp(line), template, tid, is_new))
        return parsed, {"fallback": True, "sim_th": sim_th, "template_count": len(template_seen)}

    for line in lines:
        result = miner.add_log_message(line)
        if isinstance(result, dict):
            template = result.get("template_mined") or result.get("template") or normalize_text(line)
            cluster = result.get("cluster_id", -1)
            change_type = result.get("change_type")
            change_name = change_type.name if hasattr(change_type, "name") else str(change_type)
            is_new = bool(str(change_name).lower() == "cluster_created")
        else:
            template = result.get_template()
            cluster = result.cluster.cluster_id if result.cluster is not None else -1
            is_new = bool(result.change_type.name == "cluster_created")
        tid = f"T{cluster}"
        parsed.append(ParsedEntry(line, infer_timestamp(line), template, tid, is_new))
    return parsed, {"fallback": False, "sim_th": sim_th, "template_count": len(miner.drain.clusters)}


def summarize_templates(parsed: list[ParsedEntry]) -> pd.DataFrame:
    counts = Counter(p.template for p in parsed)
    rows = []
    for template, count in counts.most_common():
        example = next(p for p in parsed if p.template == template)
        rows.append({"template_id": example.template_id, "template": template, "count": count})
    return pd.DataFrame(rows)


def tune_similarity(lines: list[str], values=(0.3, 0.5, 0.7)) -> pd.DataFrame:
    rows = []
    for sim_th in values:
        parsed, meta = parse_with_drain(lines, sim_th=sim_th)
        rows.append({"sim_th": sim_th, "template_count": meta["template_count"], "fallback": meta["fallback"]})
    return pd.DataFrame(rows)


def build_time_series(parsed: list[ParsedEntry], freq: str = "5min") -> pd.DataFrame:
    rows = [{"timestamp": p.timestamp, "template": p.template} for p in parsed if p.timestamp is not None]
    df = pd.DataFrame(rows).dropna()
    if df.empty:
        return df
    df["window"] = df["timestamp"].dt.floor(freq)
    ts = df.groupby(["window", "template"]).size().reset_index(name="count")
    return ts


def detect_anomalies(ts: pd.DataFrame, method: str = "3sigma") -> pd.DataFrame:
    if ts.empty:
        return ts
    out = ts.copy()
    if method == "3sigma":
        by_template = []
        for template, grp in out.groupby("template"):
            mu = grp["count"].mean()
            sigma = grp["count"].std(ddof=0) or 0.0
            threshold = mu + 3 * sigma
            g = grp.copy()
            g["anomaly"] = g["count"] > threshold
            g["threshold"] = threshold
            by_template.append(g)
        return pd.concat(by_template, ignore_index=True)

    feats = out[["count"]].astype(float)
    clf = IsolationForest(contamination=0.1, random_state=42)
    pred = clf.fit_predict(feats)
    out["anomaly"] = pred == -1
    out["threshold"] = None
    return out


def tfidf_similarity(templates: pd.Series) -> pd.DataFrame:
    vec = TfidfVectorizer()
    mat = vec.fit_transform(templates.astype(str))
    sim = (mat @ mat.T).toarray()
    return pd.DataFrame(sim, index=templates.index, columns=templates.index)


def recent_spikes(parsed: list[ParsedEntry], window_hours: int = 1) -> list[dict]:
    df = pd.DataFrame([{"timestamp": p.timestamp, "template": p.template} for p in parsed if p.timestamp is not None]).dropna()
    if df.empty:
        return []
    end = df["timestamp"].max()
    recent = df[df["timestamp"] >= end - pd.Timedelta(hours=window_hours)]
    prev = df[df["timestamp"] < end - pd.Timedelta(hours=window_hours)]
    rc = recent["template"].value_counts()
    pc = prev["template"].value_counts()
    rows = []
    for template, count in rc.items():
        base = pc.get(template, 0)
        ratio = count / max(base, 1)
        if ratio >= 2 or count >= 3:
            rows.append({"template": template, "recent_count": int(count), "base_count": int(base), "ratio": round(ratio, 2)})
    return rows


def new_templates_in_latest_window(parsed: list[ParsedEntry], window_hours: int = 1) -> list[str]:
    df = pd.DataFrame([{"timestamp": p.timestamp, "template": p.template} for p in parsed if p.timestamp is not None]).dropna()
    if df.empty:
        return []
    end = df["timestamp"].max()
    recent = set(df[df["timestamp"] >= end - pd.Timedelta(hours=window_hours)]["template"])
    prev = set(df[df["timestamp"] < end - pd.Timedelta(hours=window_hours)]["template"])
    return sorted(recent - prev)


def export_top_templates(df: pd.DataFrame, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)


def make_synthetic_logs() -> dict[str, list[str]]:
    d1 = [
        "[2026-06-01 09:00:01] ERROR payment timeout for order ORD-1001 from 10.0.0.1",
        "[2026-06-01 09:00:03] ERROR payment timeout for order ORD-1002 from 10.0.0.1",
        "[2026-06-01 09:05:00] INFO token validated for user USR-77 in 12ms",
        "[2026-06-01 09:10:00] WARN circuit breaker open for db-primary",
        "[2026-06-01 09:59:59] ERROR payment timeout for order ORD-1003 from 10.0.0.2",
    ] * 20
    d2 = [
        "[2026-06-01 10:00:01] INFO heartbeat OK for host node-1",
        "[2026-06-01 10:00:02] INFO heartbeat OK for host node-2",
        "[2026-06-01 10:05:03] ERROR disk read failure on /dev/sda1",
        "[2026-06-01 10:10:04] ERROR disk read failure on /dev/sda1",
        "[2026-06-01 10:20:05] WARN memory pressure high on node-2",
    ] * 16
    return {"synthetic_a": d1, "synthetic_b": d2}


def extract_block_id(text: str) -> str | None:
    m = re.search(r"(blk_-?\d+)", text)
    return m.group(1) if m else None


def load_hdfs_structured(struct_log: Path, label_file: Path | None = None) -> pd.DataFrame:
    df = pd.read_csv(struct_log)
    df["block_id"] = df["Content"].astype(str).map(extract_block_id)
    df["label"] = 0
    if label_file and label_file.exists():
        labels = pd.read_csv(label_file)
        labels["Label"] = labels["Label"].astype(str).str.lower().map({"anomaly": 1, "normal": 0}).fillna(0).astype(int)
        label_map = dict(zip(labels["BlockId"], labels["Label"]))
        df["label"] = df["block_id"].map(label_map).fillna(0).astype(int)
    return df


def hdfs_content_lines(df: pd.DataFrame) -> list[str]:
    return df["Content"].astype(str).tolist()


def parse_hdfs_with_drain(df: pd.DataFrame, sim_th: float = 0.5) -> tuple[list[ParsedEntry], dict]:
    return parse_with_drain(hdfs_content_lines(df), sim_th=sim_th)


def hdfs_session_features(df: pd.DataFrame) -> pd.DataFrame:
    seq = df.groupby("block_id").agg(
        EventSequence=("EventId", list),
        Label=("label", "max"),
        LineCount=("LineId", "count"),
    ).reset_index()
    all_events = sorted(df["EventId"].dropna().unique().tolist())
    for e in all_events:
        seq[f"feat_{e}"] = seq["EventSequence"].map(lambda xs, ev=e: int(ev in xs))
    return seq


def evaluate_binary(y_true, y_pred) -> dict[str, float]:
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average="binary", zero_division=0)
    return {"precision": float(p), "recall": float(r), "f1": float(f1)}


def parse_json_log_lines(lines: Iterable[str]) -> list[ParsedEntry]:
    parsed: list[ParsedEntry] = []
    for line in lines:
        payload = json.loads(line)
        message = str(payload.get("message") or payload.get("msg") or payload.get("log") or "")
        timestamp = payload.get("timestamp") or payload.get("@timestamp")
        parsed.append(
            ParsedEntry(
                raw=line,
                timestamp=pd.to_datetime(timestamp, errors="coerce") if timestamp else None,
                template=normalize_text(message),
                template_id=payload.get("level", "JSON"),
                is_new_template=False,
            )
        )
    return parsed


def parse_regex_log_lines(lines: Iterable[str], pattern: str, template_id: str = "REGEX") -> list[ParsedEntry]:
    rx = re.compile(pattern)
    parsed: list[ParsedEntry] = []
    for line in lines:
        match = rx.match(line)
        if match:
            template = rx.sub(lambda _: "<*>", line)
        else:
            template = normalize_text(line)
        parsed.append(
            ParsedEntry(
                raw=line,
                timestamp=infer_timestamp(line),
                template=template,
                template_id=template_id,
                is_new_template=False,
            )
        )
    return parsed


def compare_template_outputs(parsed_a: list[ParsedEntry], parsed_b: list[ParsedEntry]) -> pd.DataFrame:
    a = summarize_templates(parsed_a).rename(columns={"count": "count_a"})
    b = summarize_templates(parsed_b).rename(columns={"count": "count_b"})
    merged = a.merge(b, on="template", how="outer").fillna(0)
    merged["count_a"] = merged["count_a"].astype(int)
    merged["count_b"] = merged["count_b"].astype(int)
    return merged.sort_values(["count_a", "count_b"], ascending=False).reset_index(drop=True)
