# Contract Phụ lục F — `finops-feature-store-{env}` DynamoDB Item Schema

> **Mục đích:** Định nghĩa CHÍNH XÁC những gì bên **CDO** phải ghi (materialize) vào
> bảng DynamoDB `finops-feature-store-{env}` để **AI Engine** đọc được trong hot path
> `/v1/detect` (< 300ms, không list/get S3).
>
> **Tham chiếu:** `ai-api-contract.md` v1.5.0 §2/§5.1 (P21), `deployment-contract.md`
> §Feature Store (PK=`resource_id`, SK=`date`), `telemetry-contract.md` §7 (CUR schema).
>
> **Trạng thái:** v1.0.0 — đồng bộ với engine `statistical_detect_service.py`
> (`_compute_rolling_stats`, `_anomalies_registry`) và `schemas/detect.py`
> (`CURLineItem`, `ResourceUtilizationMetric`, `BusinessContext`).

---

## 1. Bảng & Khóa (Table & Keys)

| Thuộc tính | Giá trị |
|---|---|
| **Table name** | `finops-feature-store-{env}` — env ∈ {`prod`, `prod-core`, `prod-payments`, `staging`, `dev`, `sandbox`, `ml-research`, `data-analytics`} |
| **Engine env var** | `DYNAMODB_FEATURE_STORE_TABLE = finops-feature-store-{env}` |
| **Partition key (PK)** | `resource_id` (String) — ARN hoặc logical ID, vd `arn:aws:rds:...:db:db-1066` |
| **Sort key (SK)** | `date` (String) — `YYYY-MM-DD` (UTC, daily grain) |
| **Billing mode** | `PAY_PER_REQUEST` (on-demand) |
| **TTL attribute** | `ttl_expiry` (Number, Unix epoch giây) — auto-delete sau **35 ngày** (đủ cho rolling 28d) |
| **Engine đọc bằng** | `GetItem(PK=resource_id, SK=date)` cho 1 ngày; `Query(PK=resource_id, SK between date-28d..date)` nếu cần dựng lại lịch sử |

> ⚠️ **Một item = một (resource_id, date).** CDO ghi 1 item cho mỗi tài nguyên mỗi ngày
> ngay khi CUR của ngày đó land vào S3 (Step Functions `materialize features` task).

---

## 2. Bắt buộc — Định danh & Chi phí (Identity & Cost)

| Attribute | DynamoDB type | Bắt buộc | Nguồn (CUR) | Mô tả |
|---|---|:---:|---|---|
| `resource_id` | S (PK) | ✓ | `line_item_resource_id` | ARN/ID tài nguyên |
| `date` | S (SK) | ✓ | `line_item_usage_start_date` → `YYYY-MM-DD` | Ngày tính phí |
| `line_item_usage_account_id` | S | ✓ | same | 12 chữ số |
| `line_item_product_code` | S | ✓ | same | vd `AmazonRDS`, `AmazonEC2` |
| `line_item_usage_type` | S | ✓ | same | vd `InstanceUsage:db.r5.2xlarge` |
| `pricing_unit` | S | ✓ | same | vd `Hrs`, `GB` |
| `line_item_usage_amount` | N | ✓ | same | tổng usage trong ngày |
| `line_item_unblended_cost` | N | ✓ | same (SUM theo ngày) | **chi phí 24h** của tài nguyên |
| `is_estimated` | BOOL | ✓ | CE `is_estimated` | true → Engine trả `data_confidence=LOW` |

---

## 3. Bắt buộc — Rolling stats (CDO tính sẵn — thay S3 list/get)

> Đây là phần `deployment-contract.md` ghi *"rolling stats (thay S3 list/get cho prod)"*.
> Engine **không** tự tính lại trong hot path — nó đọc thẳng các trường này.
> Cửa sổ dùng `.shift(1)` (KHÔNG nhìn ngày hiện tại) để tránh look-ahead.

| Attribute | Type | Bắt buộc | Công thức (trên chuỗi cost theo resource) |
|---|---|:---:|---|
| `rolling_avg` | N | ✓ | mean của 7 ngày trước (`shift(1).rolling(7).mean()`) |
| `rolling_std` | N | ✓ | std 7 ngày trước (min 2 điểm; thiếu → 0) |
| `rolling_median` | N | ✓ | median 14 ngày trước |
| `rolling_mad` | N | ✓ | median(\|x − median\|) 14 ngày trước |
| `slope_14d` | N | ✓ | hệ số góc hồi quy tuyến tính 14 ngày trước (thiếu → 0) |
| `cost_pct_change_28d` | N | ✓ | `(cost − lag_28) / (lag_28 + 1e-6)` (thiếu → 0) |
| `cost_ratio_to_7d_avg` | N | ✓ | `cost / (rolling_avg + 1e-6)` |
| `absolute_cost_spike` | N | ✓ | `max(0, cost − 3·rolling_std)` |
| `peer_ratio` | N | ✓ | `cost / median(cost của cùng account+product+date)` |
| `age_days` | N | ✓ | số ngày tài nguyên đã xuất hiện (1-based) — phát hiện cold-start/A6 |

> **Cold-start (tài nguyên mới, < 14 ngày):** điền các trường thiếu bằng **median theo
> `line_item_product_code`** rồi global median (KHÔNG để `null`/`NaN`).

---

## 4. Bắt buộc — Operational metrics (gộp daily từ hourly)

> Gộp `ResourceUtilizationMetric` (hourly) → daily theo `mean`. Trường nào dịch vụ không
> có (vd S3 không có CPU) thì ghi `null`.

| Attribute | Type | Bắt buộc | Nguồn metric | Ghi chú |
|---|---|:---:|---|---|
| `cpu_mean` | N \| NULL | ✓ | mean(`cpu_percent`) | idle/runaway dùng |
| `usage_density_24h` | N | ✓ | tỉ lệ giờ active (CPU>5%) hoặc usage/24h | 0=không chạy, 1=24/24 |
| `memory_mib` | N \| NULL | ○ | mean(`memory_mib`) | |
| `network_in_bytes` | N \| NULL | ○ | mean | |
| `network_out_bytes` | N \| NULL | ○ | mean | |
| `disk_io_ops` | N \| NULL | ○ | mean | |
| `database_connections` | N \| NULL | ○ | mean | RDS/cache; RCA dùng |
| `gpu_utilization` | N \| NULL | ○ | mean | chỉ GPU instance |

---

## 5. Bắt buộc — Tag governance

| Attribute | Type | Bắt buộc | Nguồn | Mô tả |
|---|---|:---:|---|---|
| `resource_tags_user_environment` | S \| NULL | ✓ | CUR tag | null/unknown khi chưa gắn tag |
| `resource_tags_user_team` | S \| NULL | ✓ | CUR tag | thiếu → `team_missing` |
| `resource_tags_user_owner` | S \| NULL | ✓ | CUR tag | thiếu → `owner_missing` + vi phạm Tag Policy (RCA "Mis-tagged Spend") |
| `resource_tags_user_cost_center` | S \| NULL | ○ | CUR tag | dùng cho Finance allocation |

---

## 6. Metadata (bắt buộc)

| Attribute | Type | Bắt buộc | Mô tả |
|---|---|:---:|---|
| `materialized_at` | S | ✓ | ISO 8601 UTC — thời điểm CDO ghi item |
| `schema_version` | S | ✓ | `"1.0.0"` (khớp phụ lục này) |
| `ttl_expiry` | N | ✓ | Unix epoch giây = now + 35 ngày |

---

## 7. KHÔNG ghi vào feature-store — `business_context` đi theo request

> `business_context` (campaign / load_test / migration / **scheduled_backup** / **batch_etl**)
> là tín hiệu **theo batch**, gửi trong body `/v1/detect` (`BusinessContext`), **không**
> nằm trong feature-store. Đây là kênh để CDO **triệt tiêu cảnh báo giả** cho tác vụ
> hợp lệ (vd backup định kỳ → `scheduled_backup_flag: true` → Engine bỏ qua các bộ
> phát hiện cost-spike, nhưng vẫn giữ cờ tag-policy nếu tài nguyên untagged).

---

## 8. Ví dụ Item (DynamoDB JSON)

```json
{
  "resource_id":               {"S": "arn:aws:rds:us-east-1:200000000011:db:db-1066"},
  "date":                      {"S": "2026-06-10"},
  "line_item_usage_account_id":{"S": "200000000011"},
  "line_item_product_code":    {"S": "AmazonRDS"},
  "line_item_usage_type":      {"S": "InstanceUsage:db.r5.2xlarge"},
  "pricing_unit":              {"S": "Hrs"},
  "line_item_usage_amount":    {"N": "24.0"},
  "line_item_unblended_cost":  {"N": "391.25"},
  "is_estimated":              {"BOOL": false},

  "rolling_avg":               {"N": "61.13"},
  "rolling_std":               {"N": "8.42"},
  "rolling_median":            {"N": "60.10"},
  "rolling_mad":               {"N": "5.30"},
  "slope_14d":                 {"N": "1.84"},
  "cost_pct_change_28d":       {"N": "5.39"},
  "cost_ratio_to_7d_avg":      {"N": "6.40"},
  "absolute_cost_spike":       {"N": "366.0"},
  "peer_ratio":                {"N": "6.10"},
  "age_days":                  {"N": "71"},

  "cpu_mean":                  {"N": "88.0"},
  "usage_density_24h":         {"N": "0.99"},
  "memory_mib":                {"N": "24163.1"},
  "database_connections":      {"N": "190"},
  "gpu_utilization":           {"NULL": true},

  "resource_tags_user_environment": {"S": "prod-payments"},
  "resource_tags_user_team":   {"S": "squad-payments"},
  "resource_tags_user_owner":  {"NULL": true},
  "resource_tags_user_cost_center": {"S": "CC-9001"},

  "materialized_at":           {"S": "2026-06-11T02:15:00Z"},
  "schema_version":            {"S": "1.0.0"},
  "ttl_expiry":                {"N": "1783900800"}
}
```

---

## 9. Reference — Materialize Lambda (CDO side, boto3)

```python
import time, boto3
ddb = boto3.client("dynamodb", region_name="ap-southeast-1")

def put_feature(env: str, row: dict) -> None:
    """row = 1 resource-day đã tính sẵn rolling stats + metrics."""
    def num(v):  return {"N": str(v)} if v is not None else {"NULL": True}
    def s(v):    return {"S": str(v)} if v not in (None, "") else {"NULL": True}
    ddb.put_item(
        TableName=f"finops-feature-store-{env}",
        Item={
            "resource_id": {"S": row["resource_id"]},
            "date":        {"S": row["date"]},  # YYYY-MM-DD
            "line_item_usage_account_id": {"S": row["account_id"]},
            "line_item_product_code":     {"S": row["product_code"]},
            "line_item_usage_type":       {"S": row["usage_type"]},
            "pricing_unit":               {"S": row["pricing_unit"]},
            "line_item_usage_amount":     num(row["usage_amount"]),
            "line_item_unblended_cost":   num(row["cost"]),
            "is_estimated":               {"BOOL": bool(row["is_estimated"])},
            # rolling stats (CDO tính sẵn)
            "rolling_avg":          num(row["rolling_avg"]),
            "rolling_std":          num(row["rolling_std"]),
            "rolling_median":       num(row["rolling_median"]),
            "rolling_mad":          num(row["rolling_mad"]),
            "slope_14d":            num(row["slope_14d"]),
            "cost_pct_change_28d":  num(row["cost_pct_change_28d"]),
            "cost_ratio_to_7d_avg": num(row["cost_ratio_to_7d_avg"]),
            "absolute_cost_spike":  num(row["absolute_cost_spike"]),
            "peer_ratio":           num(row["peer_ratio"]),
            "age_days":             num(row["age_days"]),
            # operational metrics (daily mean)
            "cpu_mean":             num(row.get("cpu_mean")),
            "usage_density_24h":    num(row["usage_density_24h"]),
            "memory_mib":           num(row.get("memory_mib")),
            "database_connections": num(row.get("database_connections")),
            "gpu_utilization":      num(row.get("gpu_utilization")),
            # tags
            "resource_tags_user_environment":  s(row.get("environment")),
            "resource_tags_user_team":         s(row.get("team")),
            "resource_tags_user_owner":        s(row.get("owner")),
            "resource_tags_user_cost_center":  s(row.get("cost_center")),
            # metadata
            "materialized_at": {"S": row["materialized_at"]},
            "schema_version":  {"S": "1.0.0"},
            "ttl_expiry":      {"N": str(int(time.time()) + 35 * 86400)},
        },
    )
```

---

## 10. IAM (Engine read-only / CDO write)

```json
// AI Engine (read)
{ "Effect": "Allow",
  "Action": ["dynamodb:GetItem", "dynamodb:Query"],
  "Resource": "arn:aws:dynamodb:ap-southeast-1:*:table/finops-feature-store-*" }

// CDO materialize Lambda (write)
{ "Effect": "Allow",
  "Action": ["dynamodb:PutItem", "dynamodb:BatchWriteItem"],
  "Resource": "arn:aws:dynamodb:ap-southeast-1:*:table/finops-feature-store-*" }
```

> 🔒 Theo `deployment-contract.md`: dùng IAM Task Execution Role (KHÔNG static access key).

---

## 11. Checklist bàn giao (CDO ✅)

- [ ] Tạo bảng `finops-feature-store-{env}` PK=`resource_id` (S), SK=`date` (S), TTL=`ttl_expiry`.
- [ ] Step Functions task `materialize features` ghi 1 item / resource-day khi CUR land S3.
- [ ] §2–§6 đầy đủ; trường thiếu = `null`/median-impute, **không** để `NaN`.
- [ ] Set env Engine: `DYNAMODB_FEATURE_STORE_TABLE=finops-feature-store-{env}`.
- [ ] `business_context` (gồm `scheduled_backup_flag`, `batch_etl_flag`) gửi trong body `/v1/detect`.
- [ ] Smoke: `GetItem` 1 resource-day → đủ trường §2–§6 → gọi `/v1/detect` 200.
