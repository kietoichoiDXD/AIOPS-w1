# Formal Change Request — Contract v3.2 Production Hardening

| Field | Value |
|---|---|
| **CR ID** | CR-TF2-2026-0625-v3.2 |
| **Date** | 2026-06-25 |
| **Requested by** | AI Team (AIO2) |
| **Approvers** | AI Lead + CDO-01 Lead + CDO-02 Lead |
| **Risk class** | Public API / external contract change (vc-risk-evidence-pack) |
| **Bump** | telemetry 3.1.0 → **3.2.0**, api 1.3.0 → **1.4.0**, deployment 1.2.0 → **1.3.0** |

---

## Summary

Nâng cấp contracts từ capstone-ready lên production-ready: DynamoDB idempotency, account-scoped S3 buckets, CUR-CE mismatch detail, traffic_volume spec, cost_per_request normalization.

---

## Changes

### Breaking (minor bump)

1. `business_context` thêm `linked_account_id`, `traffic_source` (required)
2. `telemetry_delay_event=true` yêu cầu `missing_resources`, `current_ce_cost_gap_usd`, `comparison_window`
3. Idempotency store: S3 → **DynamoDB** hot path
4. S3 bucket pattern: `company-cdo-{account_id}-telemetry`

### Non-breaking

5. Signal 1 aligned CSV (30-day CE, region optional)
6. Signal 2 aligned CSV (`line_item_resource_id` optional)
7. CloudWatch metrics: only `resource_id` required
8. Feature store: DynamoDB recommended for prod

---

## Rollback Plan

Revert to git tag `contract-v1.2.0-freeze` nếu CDO chưa kịp implement DynamoDB — tạm dùng S3 idempotency với documented latency trade-off.

---

## Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| AI Lead | | | |
| CDO-01 Lead | | | |
| CDO-02 Lead | | | |

---

*CR-TF2-2026-0625-v3.2*
