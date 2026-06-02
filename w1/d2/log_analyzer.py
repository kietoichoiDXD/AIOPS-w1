from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd


TIMESTAMP_PATTERNS = [
    re.compile(r"^\[(?P<ts>[^\]]+)\]"),
    re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"),
]

TOKEN_PATTERNS = [
    (re.compile(r"\b\d+\.\d+\.\d+\.\d+\b"), "<IP>"),
    (re.compile(r"\b\d{1,5}\b"), "<NUM>"),
    (re.compile(r"\b[0-9a-f]{8,}\b", re.IGNORECASE), "<HEX>"),
    (re.compile(r"\b[A-Z]{2,}-\d+\b"), "<ID>"),
]


@dataclass(frozen=True)
class ParsedLine:
    raw: str
    template: str
    timestamp: pd.Timestamp | None = None


def load_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")
    return [line.rstrip("\n") for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]


def extract_timestamp(line: str) -> pd.Timestamp | None:
    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.search(line)
        if match:
            return pd.to_datetime(match.group("ts"), errors="coerce")
    return None


def normalize_line(line: str) -> str:
    text = line.strip()
    for pattern, replacement in TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_lines(lines: Iterable[str]) -> list[ParsedLine]:
    parsed: list[ParsedLine] = []
    for line in lines:
        parsed.append(
            ParsedLine(
                raw=line,
                template=normalize_line(line),
                timestamp=extract_timestamp(line),
            )
        )
    return parsed


def parse_csv_log(path: Path) -> list[ParsedLine]:
    df = pd.read_csv(path)
    if "Content" in df.columns:
        lines = df["Content"].astype(str).tolist()
        timestamps = [None] * len(lines)
        if "Date" in df.columns and "Time" in df.columns:
            timestamps = [pd.NaT] * len(lines)
        parsed = []
        for line, ts in zip(lines, timestamps):
            parsed.append(ParsedLine(raw=line, template=normalize_line(line), timestamp=ts))
        return parsed
    return parse_lines(df.astype(str).agg(" ".join, axis=1).tolist())


def summarize(parsed: list[ParsedLine], top_k: int = 5) -> dict:
    template_counts = Counter(item.template for item in parsed)
    unique_templates = len(template_counts)
    total_lines = len(parsed)
    top_templates = [
        {
            "template": template,
            "count": count,
            "ratio": round(count / total_lines, 4) if total_lines else 0.0,
        }
        for template, count in template_counts.most_common(top_k)
    ]

    template_positions: dict[str, list[int]] = defaultdict(list)
    for idx, item in enumerate(parsed):
        template_positions[item.template].append(idx)

    recent_window = max(1, total_lines // 10)
    recent_slice = parsed[-recent_window:]
    recent_counts = Counter(item.template for item in recent_slice)
    mean_recent = (recent_window / max(unique_templates, 1)) if unique_templates else 0
    spike_templates = [
        {
            "template": template,
            "recent_count": count,
            "total_count": template_counts[template],
        }
        for template, count in recent_counts.items()
        if count >= max(3, mean_recent * 2)
    ]

    seen_before = {item.template for item in parsed[:-recent_window]}
    new_templates = sorted(set(recent_counts) - seen_before)

    return {
        "total_lines": total_lines,
        "unique_templates": unique_templates,
        "top_templates": top_templates,
        "spike_templates": spike_templates,
        "new_templates": new_templates,
    }


def write_outputs(summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "top_templates.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["template", "count", "ratio"])
        writer.writeheader()
        writer.writerows(summary["top_templates"])
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mini log analyzer for W1-D2")
    parser.add_argument("log_file", help="Path to a log file")
    parser.add_argument("--out-dir", default="artifacts/outputs", help="Output directory")
    args = parser.parse_args()

    log_path = Path(args.log_file)
    out_dir = Path(args.out_dir)

    if log_path.suffix.lower() == ".csv":
        parsed = parse_csv_log(log_path)
    else:
        parsed = parse_lines(load_lines(log_path))
    summary = summarize(parsed)
    write_outputs(summary, out_dir)

    print(f"Total lines: {summary['total_lines']}")
    print(f"Unique templates: {summary['unique_templates']}")
    print("Top templates:")
    for item in summary["top_templates"]:
        print(f"- {item['count']:>6} | {item['ratio']:.2%} | {item['template']}")
    if summary["spike_templates"]:
        print("Spike templates:")
        for item in summary["spike_templates"]:
            print(f"- {item['template']} | recent={item['recent_count']} | total={item['total_count']}")
    if summary["new_templates"]:
        print("New templates in latest window:")
        for template in summary["new_templates"]:
            print(f"- {template}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
