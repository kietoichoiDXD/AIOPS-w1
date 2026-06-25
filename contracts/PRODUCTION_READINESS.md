# Production Readiness Gate — TF2 FinOps Watch Contracts

<!-- Method: vc-autoresearch (domain: spec) + vc-risk-evidence-pack
     Generated: 2026-06-25
     Canonical contracts: AIO2/ only -->

## TL;DR

Bộ contract `AIO2/` đạt **production gate** khi tất cả mục **P0** trong checklist dưới đây = ✅. Hiện tại: **P0 implementation-ready**, **P1 cần CI + backtest synthetic traffic**.

---

## Canonical Source of Truth

| Document | Version | Path |
|---|---|---|
| AI API Contract | **v1.4.0** | `AIO2/ai-api-contract.md` |
| Telemetry Contract | **v3.2.0** | `AIO2/telemetry-contract.md` |
| Deployment Contract | **v1.3.0** | `AIO2/deployment-contract.md` |

> `capstone-phase2/contracts/` = **archive/template only**. Không implement từ đó.

Formal change log: `AIO2/CHANGE_REQUEST_v3.2.md`

---

## Production Checklist

### P0 — Must pass before FREEZE v2

| # | Gate | Status | Evidence |
|---|---|---|---|
| 1 | Single canonical path (`AIO2/`) | ✅ | `capstone-phase2/contracts/README.md` |
| 2 | Cross-contract version matrix aligned | ✅ | `CROSS_CONTRACT_SYNC_REPORT.md` |
| 3 | Idempotency = DynamoDB hot path | ✅ | telemetry §4, api §3.2, deployment §Appendix C |
| 4 | S3 bucket globally unique pattern | ✅ | `company-cdo-{account_id}-telemetry` |
| 5 | Signal 1/2 match TF2 CSV | ✅ | telemetry §6, §7 |
| 6 | CUR-CE mismatch fields when delay | ✅ | telemetry §6.2, api §5.1 |
| 7 | `traffic_volume` collection spec | ✅ | telemetry §11.2 |
| 8 | `cost_per_request` feature pipeline | ✅ | telemetry §11.1 |
| 9 | SLO consistent (300ms detect) | ✅ | `01_requirements.md` §6 |
| 10 | Security boundaries (prod/IAM/data) | ✅ | api §3, deployment §CDO IAM |

### P1 — Must pass before production deploy

| # | Gate | Status | Action |
|---|---|---|---|
| 11 | JSON Schema CI validator | ✅ | `tools/validate_contracts.py` |
| 12 | Synthetic traffic for backtest | ⚠️ | Run `tools/generate_synthetic_traffic.py` |
| 13 | Pact/consumer contract tests | ⬜ | CDO team — defer W12 |
| 14 | DynamoDB tables provisioned | ⬜ | IaC: idempotency + feature-store |
| 15 | Feature store production path | ⬜ | DynamoDB PK/SK (deployment §Appendix C) |
| 16 | OpenAPI 3.x export | ⬜ | Optional v2.0 |

### P2 — Production hardening (post-capstone)

| # | Item |
|---|---|
| 17 | DLQ for malformed detect payloads |
| 18 | Idempotency stale-lock CloudWatch alarm |
| 19 | ADR defend gap thresholds (1%, 10%) |
| 20 | Per-service traffic attribution (not just account) |

---

## Skills Applied (D-Shiftify)

| Skill | Application |
|---|---|
| `vc-autoresearch` | Gap loop: find → fix → verify across 3 contracts |
| `vc-generate-spec` | Production gate acceptance criteria |
| `vc-risk-evidence-pack` | Contract change = public API high-risk class |
| `vc-feasibility-test` | DynamoDB idempotency + traffic_volume feasibility |
| `vc-sequential-thinking` | Benign vs anomaly classification design |

---

## Verification Commands

```bash
# 1. Cross-contract alignment check
python AIO2/tools/validate_contracts.py

# 2. Generate synthetic traffic for backtest
python AIO2/tools/generate_synthetic_traffic.py

# 3. Verify synthetic traffic correlates with cost
python -c "import pandas as pd; t=pd.read_csv('capstone-phase2/data/tf2-finops/synthetic_traffic_daily.csv'); print(t.describe())"
```

---

*Production Readiness Gate — TF2 FinOps Watch — 2026-06-25*
