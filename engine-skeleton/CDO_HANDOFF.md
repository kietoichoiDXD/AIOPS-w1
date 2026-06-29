# AI Engine — CDO Handoff (FinOps Watch, TF2)

> Bản bàn giao AI Engine cho CDO Platform. AI Engine là service đồng bộ CDO gọi để
> phát hiện anomaly chi phí, lập kế hoạch can thiệp, và xác thực kết quả.
>
> **Contract:** `ai-api-contract.md` **v1.5.0** (canonical: `AIO2/`).
> **Status:** 55 passed / 1 skipped · contract validator ✅ all green · OpenAPI `openapi.json`.

---

## 1. Những gì CDO nhận

| Thành phần | Đường dẫn | Mô tả |
|---|---|---|
| AI Engine (FastAPI) | `capstone-phase2/engine-skeleton/` | Service CDO gọi — 6 endpoint, chạy ngay không cần model file |
| OpenAPI spec | `engine-skeleton/openapi.json` | Import vào Postman/Swagger để sinh client |
| AI overlay model | `AIO2/ai-engine/artifacts/overlay_model.joblib` | Tín hiệu ML phụ (weight 0.30), bật qua env |
| Evidence study | `AIO2/ai-engine/artifacts/comparison_report.md` | Bằng chứng phương pháp detect cho mentor |

Detection mặc định = **statistical detectors trên hành vi cost** (không cần CPU/mem
synthetic). ML overlay là tín hiệu phụ, không phải bộ phán quyết — lý do ở §6.

---

## 2. Endpoints (contract §5)

| Method | Path | Vai trò |
|---|---|---|
| `GET`  | `/health` | Health check cho ALB/ECS |
| `POST` | `/v1/detect` | Phát hiện anomaly (đồng bộ, P99 < 300ms, **không** gọi Bedrock) |
| `POST` | `/v1/decide` | Lập kế hoạch can thiệp + RCA |
| `POST` | `/v1/verify` | Xác thực sau hành động (DONE/RETRY/ROLLBACK/ESCALATE) |
| `GET`  | `/v1/status/{anomaly_id}` | Poll trạng thái remediation |
| `POST` | `/v1/audit/{audit_id}/rollback` | Ghi nhận rollback thủ công (FP feedback) |

Headers bắt buộc (mọi request §4): `X-Tenant-Id`, `X-Idempotency-Key`,
`X-Payload-SHA256`, `X-Request-Timestamp` (RFC3339, skew ≤ 300s), `X-Dry-Run-Mode`.
Idempotency key dùng suffix theo bước: `{tenant}:{date}:detect|decide|verify` (§3.2).

---

## 3. Chạy engine

```bash
cd capstone-phase2/engine-skeleton
pip install -r requirements.txt
# (tuỳ chọn) bật AI overlay — dùng metric của Khoa làm tín hiệu phụ:
export AI_OVERLAY_MODEL="../../AIO2/ai-engine/artifacts/overlay_model.joblib"   # PowerShell: $env:AI_OVERLAY_MODEL=...
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Swagger UI: http://localhost:8000/docs    | OpenAPI: http://localhost:8000/openapi.json
```
Docker: `docker compose up` (xem `docker-compose.yml` + `Dockerfile`).

---

## 4. Ví dụ gọi `/v1/detect`

**Request (RAW_JSON, CUR sẵn sàng):**
```json
{
  "data_source_type": "RAW_JSON",
  "telemetry_delay_event": false,
  "business_context": {
    "linked_account_id": "200000000012", "traffic_volume": 1250000,
    "traffic_source": "ALB", "campaign_flag": false,
    "load_test_flag": false, "migration_flag": false
  },
  "aws_cur_line_items": [{
    "line_item_usage_start_date": "2026-06-23T00:00:00Z",
    "line_item_usage_account_id": "200000000012",
    "line_item_product_code": "AmazonEC2",
    "line_item_usage_type": "BoxUsage:p3.2xlarge",
    "line_item_resource_id": "i-0fbgpu00000004",
    "line_item_usage_amount": 24.0, "pricing_unit": "Hrs",
    "line_item_unblended_cost": 1468.8, "usage_density_24h": 1.0,
    "resource_tags_user_environment": "ml-research"
  }],
  "resource_utilization_metrics": [{
    "resource_id": "i-0fbgpu00000004", "cpu_percent": 96.0,
    "cpu_utilization_hourly": [96, 96, "... 24 phần tử ..."],
    "memory_mib": 60000, "gpu_utilization": 99.0
  }]
}
```

**Response 200 (mẫu thật từ engine):**
```json
{
  "success": true,
  "correlation_id": "1bf8f87d-31c6-46db-b1dd-edb1f00165b8",
  "anomalies_detected": true,
  "data_confidence": "HIGH",
  "anomalies_list": [{
    "anomaly_id": "ANM-2026-0629S", "anomaly_type": "untagged_spend",
    "severity": "HIGH", "confidence_score": 0.82,
    "resource_id": "i-0fbgpu00000004", "environment": "ml-research",
    "responsible_team": null, "unblended_cost_24h_usd": 1468.8,
    "cost_ratio_to_7d_avg": 1.0,
    "ai_model_used": "statistical+overlay",
    "alert_routing": { "finance": true, "engineering": true }
  }],
  "error_message": null
}
```

**Lưu ý dữ liệu (đã cập nhật theo v1.5.0):**
- `business_context` **bắt buộc mỗi batch**.
- `aws_cost_explorer_daily` + `missing_resources` + `current_ce_cost_gap_usd` +
  `comparison_window` chỉ bắt buộc khi `telemetry_delay_event = true` (CE fallback →
  `data_confidence = "LOW"`).
- Daily batch lớn dùng `S3_POINTER`: `s3://company-cdo-{account_id}-telemetry/...` với đuôi `.csv.gz` (native CUR) **hoặc** `.json.gz` (Athena) — engine auto-detect.
- CDO gửi `cpu_utilization_hourly` (24 phần tử thô); AI Engine tự tính idle streak.

### Đường dữ liệu CUR (chốt: 2 chế độ)

Chỉ còn **2 chế độ** CDO cần nhớ. Phương án B và C đã **gộp làm một** đường
`S3_POINTER` — engine **tự nhận dạng format theo đuôi file**, CDO gửi kiểu nào cũng
chạy cùng một endpoint, cùng một field `s3_bucket_uri`.

| Chế độ | Khi nào dùng | CDO làm gì | Engine |
|---|---|---|---|
| **RAW_JSON** (A) | Ad-hoc / demo, payload ≤ 10MB | Parse CUR → nhét rows vào `aws_cur_line_items` | đọc rows inline |
| **S3_POINTER** (B+C gộp) | **Daily batch** (SLO 300ms) | Upload file lên S3 rồi gửi `s3_bucket_uri` | fetch → giải nén → parse → detect |

Trong **S3_POINTER**, `s3_bucket_uri` chấp nhận **cả 2 format** (pattern
`…\.(json\|csv)\.gz$`), engine auto-detect:

| Đuôi file | Nguồn | CDO có phải convert? |
|---|---|---|
| `.csv.gz` | **Native AWS CUR 2.0** (AWS giao thẳng vào S3) | ❌ **Không** — chỉ trỏ pointer |
| `.json.gz` | Athena query → UNLOAD (JSON-array **hoặc** JSON-lines) | ✅ Có (nếu đã có pipeline Athena) |

> **Khuyến nghị:** không có sẵn Athena → gửi thẳng `.csv.gz` native CUR (zero convert).
> Đã có pipeline Athena/feature-store → gửi `.json.gz`. **Cùng một request**, engine
> không phân biệt — chọn theo hạ tầng sẵn có của CDO. (CUR **2.0** để cột khớp `line_item_*`.)

- Engine fetch S3 qua `boto3` (IAM role). Test/offline: set `S3_LOCAL_DIR` để đọc
  `{S3_LOCAL_DIR}/{key}` thay cho AWS — pipeline chạy không cần S3 thật.
- Fetch/parse lỗi → trả `[]` (no anomalies), không bao giờ 500.

### Kết nối AWS (cho S3_POINTER)

1. **CUR delivery**: cấu hình AWS CUR 2.0 ghi vào bucket
   `company-cdo-{account_id}-telemetry` (hoặc copy CUR sang đó). Format `Gzip` (.csv.gz).
2. **IAM** cho execution role của AI Engine (ECS Fargate task role) — đúng
   `deployment-contract §3.4`:
   ```json
   { "Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"],
     "Resource": ["arn:aws:s3:::company-cdo-*-telemetry",
                  "arn:aws:s3:::company-cdo-*-telemetry/*"] }
   ```
   Không hardcode access key — Engine dùng role (`boto3` tự lấy credential chain).
3. **Env**: `AWS_DEFAULT_REGION=ap-southeast-1`. `pip install boto3` (đã có trong `requirements.txt`).
4. **Smoke test kết nối** (chạy trên môi trường có role/credential):
   ```bash
   python -c "import boto3; print(boto3.client('s3').head_object(Bucket='company-cdo-200000000012-telemetry', Key='cur/cdo-02/2026-06-23.csv.gz'))"
   ```
   OK → gọi `/v1/detect` với `data_source_type=S3_POINTER` + `s3_bucket_uri` trỏ file đó.

---

## 5. Đã đồng bộ contract trong lần bàn giao này

| Thay đổi | Trước | Sau (v1.5.0) |
|---|---|---|
| `business_context` | thiếu | **required** trên `/v1/detect` |
| `data_confidence` | thiếu | **required** trong `DetectResponse` (HIGH/LOW) |
| CE fallback fields | thiếu | `missing_resources`, `current_ce_cost_gap_usd`, `comparison_window` |
| `callback_url` / `callback_token` | thiếu | optional, đã thêm |
| S3 bucket pattern | `tf2-cdo…` (cũ) | `company-cdo-{account_id}-telemetry` |
| `/v1/status` | chỉ `audit_id` (ANM-) | tách `audit_id` (UUID) **và** `anomaly_id` (ANM-) |
| Field quá chặt | CE/CUR/utilization required dư | nới đúng `required` của contract |
| Validator + version | còn ghi v1.4.0 | v1.5.0, `validate_contracts.py` ✅ |

Kiểm chứng: `python AIO2/tools/validate_contracts.py` · `pytest` (trong engine-skeleton).

---

## 5b. Safety guard & multi-tenant (W12 T2 — CDO phải handle)

Hai cơ chế cross-cutting vừa được enforce trong engine, CDO cần xử lý ở client:

**Multi-tenant isolation (§4).** `X-Tenant-Id` phải là chuỗi dạng UUID (8-4-4-4-12 hex);
sai format → `400 ERR_INVALID_SCHEMA`. Anomaly được "sở hữu" bởi tenant đã gọi `/v1/detect`
sinh ra nó. Nếu tenant khác gọi `/v1/decide`, `/v1/status/{id}` hay `/rollback` trên
anomaly đó → **`403 ERR_CROSS_TENANT_DENIED`** (chặn ngay, là cảnh báo bảo mật).
Anomaly ID lạ/chưa từng thấy thì **không** bị chặn (cho phép replay/historical).

**Error-budget LOCKED_MODE (§3.2).** Rollback (false-positive) làm hao error budget theo
`(tenant, env)`: prod > 1%, staging > 10%, các env khác unlimited. Khi vượt ngưỡng tenant
chuyển **LOCKED_MODE**:

- `/v1/decide` bị **ép `dry_run_mode: true`** và downgrade về `tag-for-review` — không bao
  giờ phát lệnh shutdown/quota thật, kể cả khi CDO gửi `X-Dry-Run-Mode: false`.
- Response **kèm header `X-Containment-Status: LOCKED`** + `X-Lock-Reason: error_budget_exceeded`
  (giờ xuất hiện cả trên `/v1/decide`, không chỉ `/v1/status`).
- CDO khi thấy header này: **không execute** `aws_cli_command`, hiển thị trạng thái LOCKED,
  chờ AI Team Lead unlock thủ công.

`/v1/status/{id}` phản ánh `containment_locked` + `error_budget_remaining_pct` **live** theo
tenant sở hữu anomaly.

**Rate limit (§3).** Engine giới hạn **100 req/phút per tenant** (env `RATE_LIMIT_PER_MIN`,
defence-in-depth cạnh ALB/API Gateway). Vượt → **`429 ERR_RATE_LIMITED`** kèm header
`Retry-After` (giây). CDO xử lý bằng **exponential backoff** 1s→2s→4s→8s→16s. Đặt
`RATE_LIMIT_PER_MIN=0` để tắt (chỉ dùng cho test).

---

## 6. Methodology & lưu ý trung thực (đọc trước khi tin số)

- **Detect chính = statistical trên cost behaviour.** Model ML train trên nhãn metric
  synthetic chỉ đạt ~0.12 precision trên **nhãn cost ẩn** mentor chấm
  (`AIO2/REVIEW_v2_detect_anomaly.md §4b`) → vì vậy ML chỉ là **overlay weight 0.30**.
- **Evidence study** (`AIO2/ai-engine/`): trên nhãn metric đầy đủ, gắn nhãn **theo
  window** + supervised đạt P0.88/R0.70/F10.78; per-point/unsupervised ≤ F1 0.22.
  Đây là bằng chứng phương pháp, không phải số trên backtest cost ẩn.
- Khi data chốt: chạy AutoML trên cùng split, thay sequence-MLP bằng LSTM thật,
  bơm chaos/synthetic anomaly để tăng coverage, re-score overlay trên nhãn cost
  trước khi nâng weight > 0.30.

---

## 7. Danh sách file gửi CDO

1. `capstone-phase2/engine-skeleton/` (toàn bộ service + `openapi.json` + `CDO_HANDOFF.md` này)
2. `AIO2/ai-api-contract.md` v1.5.0 (+ `telemetry-contract.md`, `deployment-contract.md`)
3. `AIO2/ai-engine/artifacts/overlay_model.joblib` (+ `comparison_report.md` làm evidence)
4. `AIO2/aio-cdo-workflow.md` (luồng AI ↔ CDO)
