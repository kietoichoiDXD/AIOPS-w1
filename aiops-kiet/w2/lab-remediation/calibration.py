"""Confidence calibration for the remediation engine.

Reads audit.jsonl + eval/expected.json, computes:
  - per-incident: predicted confidence, hit (1/0)
  - reliability diagram (binned)
  - Platt scaling: sigmoid fit on raw scores -> calibrated probabilities
  - ECE (Expected Calibration Error) before and after

Usage:
    python calibration.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path


def _is_hit(entry: dict, expected: dict) -> int:
    inc_id = entry["incident_id"]
    exp = expected.get(inc_id, {})
    action = entry["selected_action"]
    params = entry.get("params", {})
    for acc in exp.get("accepted_actions", []):
        if acc["name"] != action:
            continue
        match = all(
            str(params.get(k, "")).lower() in (str(v).lower(), "")
            for k, v in acc.get("params", {}).items()
        )
        if match:
            return 1
    return 0


def reliability_diagram(predicted: list[float], actual: list[int], n_bins: int = 4) -> list[dict]:
    bins: dict[int, list] = {i: [] for i in range(n_bins)}
    for p, a in zip(predicted, actual):
        b = min(int(p * n_bins), n_bins - 1)
        bins[b].append((p, a))
    result = []
    for b, pairs in bins.items():
        if not pairs:
            continue
        lo, hi = b / n_bins, (b + 1) / n_bins
        mean_pred = sum(p for p, _ in pairs) / len(pairs)
        hit_rate = sum(a for _, a in pairs) / len(pairs)
        result.append({
            "bin": f"[{lo:.2f}, {hi:.2f})",
            "n": len(pairs),
            "mean_confidence": round(mean_pred, 4),
            "actual_hit_rate": round(hit_rate, 4),
            "gap": round(hit_rate - mean_pred, 4),
        })
    return result


def ece(predicted: list[float], actual: list[int], n_bins: int = 4) -> float:
    n = len(predicted)
    bins: dict[int, list] = {i: [] for i in range(n_bins)}
    for p, a in zip(predicted, actual):
        b = min(int(p * n_bins), n_bins - 1)
        bins[b].append((p, a))
    total = 0.0
    for pairs in bins.values():
        if not pairs:
            continue
        acc = sum(a for _, a in pairs) / len(pairs)
        conf = sum(p for p, _ in pairs) / len(pairs)
        total += (len(pairs) / n) * abs(acc - conf)
    return round(total, 4)


def platt_scale(scores: list[float], labels: list[int]) -> tuple[float, float]:
    """Fit sigmoid: P(correct) = 1 / (1 + exp(-(A*s + B))).
    Uses gradient descent since sklearn may not be available.
    Returns (A, B).
    """
    A, B = 1.0, 0.0
    lr = 0.5
    for _ in range(2000):
        dA = dB = 0.0
        for s, y in zip(scores, labels):
            p = 1.0 / (1.0 + math.exp(-(A * s + B)))
            err = p - y
            dA += err * s
            dB += err
        A -= lr * dA / len(scores)
        B -= lr * dB / len(scores)
    return round(A, 4), round(B, 4)


def apply_platt(scores: list[float], A: float, B: float) -> list[float]:
    return [round(1.0 / (1.0 + math.exp(-(A * s + B))), 4) for s in scores]


def main() -> None:
    audit = [json.loads(l) for l in Path("audit.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    expected = json.loads(Path("eval/expected.json").read_text(encoding="utf-8"))

    predicted = [e["confidence"] for e in audit]
    actual = [_is_hit(e, expected) for e in audit]

    print("=== Per-incident ===")
    for e, a in zip(audit, actual):
        print(f"  {e['incident_id']:4s}  conf={e['confidence']:.4f}  hit={a}  action={e['selected_action']}")

    print("\n=== Reliability Diagram (before calibration) ===")
    diagram = reliability_diagram(predicted, actual)
    for row in diagram:
        bar = "█" * int(abs(row["gap"]) * 40)
        direction = "over" if row["gap"] < 0 else "under"
        print(f"  {row['bin']}  n={row['n']}  pred={row['mean_confidence']:.3f}  actual={row['actual_hit_rate']:.3f}  gap={row['gap']:+.3f} ({direction}) {bar}")

    ece_before = ece(predicted, actual)
    print(f"\nECE before calibration: {ece_before}")

    A, B = platt_scale(predicted, actual)
    calibrated = apply_platt(predicted, A, B)
    print(f"\n=== Platt Scaling: A={A}, B={B} ===")
    print("  Calibrated confidences:")
    for e, raw, cal, a in zip(audit, predicted, calibrated, actual):
        print(f"  {e['incident_id']:4s}  raw={raw:.4f} -> cal={cal:.4f}  hit={a}")

    print("\n=== Reliability Diagram (after calibration) ===")
    diagram_cal = reliability_diagram(calibrated, actual)
    for row in diagram_cal:
        bar = "█" * int(abs(row["gap"]) * 40)
        direction = "over" if row["gap"] < 0 else "under"
        print(f"  {row['bin']}  n={row['n']}  pred={row['mean_confidence']:.3f}  actual={row['actual_hit_rate']:.3f}  gap={row['gap']:+.3f} ({direction}) {bar}")

    ece_after = ece(calibrated, actual)
    print(f"\nECE after calibration:  {ece_after}")
    print(f"ECE improvement:        {round(ece_before - ece_after, 4)}")


if __name__ == "__main__":
    main()
