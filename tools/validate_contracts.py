#!/usr/bin/env python3
"""
Contract alignment validator — TF2 FinOps Watch
Run: python AIO2/tools/validate_contracts.py
Exit 0 = all checks pass (production gate P1)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AIO2 = ROOT / "AIO2"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> int:
    api = read(AIO2 / "ai-api-contract.md")
    telem = read(AIO2 / "telemetry-contract.md")
    deploy = read(AIO2 / "deployment-contract.md")
    reqs = read(AIO2 / "01_requirements.md")

    # Version matrix
    check("api version v1.4.0", "Version: v1.4.0" in api, "")
    check("telemetry version v3.2.0", "3.2.0" in telem[:2000], "")
    check("deployment version v1.3.0", "v1.3.0" in deploy[:800], "")

    # Idempotency DynamoDB
    check("api idempotency DynamoDB", "finops-idempotency" in api, "")
    check("telemetry idempotency DynamoDB", "DynamoDB conditional write" in telem, "")
    check("deployment idempotency DynamoDB", "Appendix C" in deploy and "finops-idempotency" in deploy, "")

    # Bucket pattern
    pattern = "company-cdo-{account_id}-telemetry"
    check("bucket pattern all contracts", all(pattern in c for c in [api, telem, deploy]), "")

    # CUR-CE mismatch
    for field in ("missing_resources", "current_ce_cost_gap_usd", "comparison_window"):
        check(f"field {field}", field in api and field in telem, "")

    # Business context
    for field in ("traffic_volume", "traffic_source", "linked_account_id", "cost_per_request"):
        in_telem = field in telem
        in_api = field in api if field != "cost_per_request" else "cost_per_request" in telem
        check(f"business/feature {field}", in_telem and (field == "cost_per_request" or in_api), "")

    # CUR schema sync
    for col in ("product_region_code", "line_item_currency_code", "bill_payer_account_id"):
        check(f"CUR column {col}", col in api and col in telem, "")

    # SLO consistency
    check("SLO 300ms detect", "300ms" in reqs and "300 ms" in api, "")
    check("no stale 50ms async SLO", "50\\text{ms}" not in reqs and "< 50" not in reqs, "")

    # No legacy-only idempotency in deployment secrets
    check("deployment no S3-only idempotency", "idempotency, audit logs" not in deploy, "")

    # Canonical pointer
    capstone_readme = ROOT / "capstone-phase2" / "contracts" / "README.md"
    check("capstone canonical pointer", capstone_readme.exists() and "NOT Canonical" in read(capstone_readme), "")

    # Production gate doc
    check("PRODUCTION_READINESS.md exists", (AIO2 / "PRODUCTION_READINESS.md").exists(), "")

    # CSV alignment — CE columns
    ce_csv = ROOT / "capstone-phase2" / "data" / "tf2-finops" / "cost_explorer_daily.csv"
    if ce_csv.exists():
        header = ce_csv.read_text(encoding="utf-8").splitlines()[0]
        for col in ("date", "linked_account_id", "service_code", "unblended_cost", "is_estimated"):
            check(f"CE CSV column {col}", col in header, "")

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)
    print(f"\nContract Validation: {passed}/{total} checks passed\n")
    for name, ok, detail in CHECKS:
        status = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"  [{status}] {name}{suffix}")

    if passed < total:
        print(f"\n❌ {total - passed} check(s) failed — not production-ready")
        return 1
    print("\n✅ All contract alignment checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
