from __future__ import annotations


def parse_history_action(s: str) -> dict:
    parts = s.split(":")
    if not parts:
        return {"name": "page_oncall", "params": []}
    return {"name": parts[0], "params": parts[1:]}


def parse_metric_delta(s: str) -> tuple[float, float]:
    parts = s.replace("->", "|").split("|")
    if len(parts) != 2:
        raise ValueError(f"unexpected delta format: {s!r}")
    return float(parts[0].strip()), float(parts[1].strip())
