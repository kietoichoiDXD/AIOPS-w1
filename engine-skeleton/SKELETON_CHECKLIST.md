# Engine Skeleton — Checklist & Insight Notes

> **Mục đích**: File này giúp toàn bộ thành viên AIOps, DevOps, CloudOps trong Task Force 2 hiểu rõ engine skeleton giải quyết vấn đề gì, kiểm tra đúng/sai, và biết được ranh giới trách nhiệm giữa các nhóm.
>
> **Ngày tạo**: 2026-06-23 (W11 T2)
> **Trạng thái**: Skeleton (dummy logic) — sẽ chuyển sang real logic trong W12

---

## 1. Engine Skeleton giải quyết vấn đề gì?

### Vấn đề cốt lõi

Theo flow capstone, nhóm AI phải deploy **engine skeleton** vào chiều **Thứ 5 W11** để CDO có endpoint thật mà tích hợp ngay từ **Thứ 6 W11**, thay vì chờ AI hoàn thành logic thật (sẽ kéo đến W12 T3).

Nếu **không có skeleton**:
- CDO bị **block 5–6 ngày** không thể tích hợp, test pipeline, hay build dashboard.
- Lúc tích hợp thật vào W12 T3 (Integration Session) sẽ phát hiện lỗi schema, lỗi routing, lỗi authentication → **không kịp sửa trước code freeze**.

### Skeleton giải quyết bằng cách

| Vấn đề | Cách skeleton xử lý |
|---|---|
| CDO chưa có endpoint để gọi | Skeleton cung cấp endpoint thật `POST /v1/finops/detect` trả về JSON đúng schema |
| CDO không biết response trông như thế nào | Response schema **giống hệt** real engine: `anomaly`, `severity`, `confidence`, `finance_summary`, `engineering_summary`, `alert_route`, `suggested_action`, `audit_id` |
| CDO cần test authentication flow | Skeleton enforce `X-Tenant-Id` header, trả 400 nếu thiếu — giống behavior thật |
| CDO cần verify error handling | Skeleton trả đúng error codes: 400 (bad request), 422 (validation), 503 (engine down) |
| W12 chuyển sang real logic sẽ break CDO? | **Không** — URL không đổi, schema không đổi, CDO không cần sửa gì |

### Một câu tóm tắt

> Engine skeleton là **mock server thật** chạy trên AWS, trả response đúng contract, để CDO build infra song song với AI mà không bị block — khi AI thay dummy bằng real logic, CDO không cần thay đổi gì.

---

## 2. Checklist kiểm tra Skeleton (cho toàn team)

### ✅ Contract Compliance — Schema có đúng contract không?

- [ ] **Endpoint path đúng**: `POST /v1/finops/detect` (khớp với AI API Contract §Endpoint 1 và Operating Flow §6)
- [ ] **Health check path đúng**: `GET /health` trên port `8080` (khớp Deployment Contract §Health check)
- [ ] **Request schema** có đủ các fields theo Telemetry Contract TF2:
  - [ ] `cost_window[]` chứa: `account_id`, `service`, `region`, `cost_usd`, `usage_type`, `tags`, `environment`, `owner`, `cost_period_start`, `cost_period_end`
  - [ ] `baseline` metadata: `baseline_start`, `baseline_end`, `baseline_avg_daily_cost_usd`
  - [ ] `detection_cadence_hours` (12/24/48)
  - [ ] `containment_policy` (optional)
- [ ] **Response schema** có đủ các fields theo Operating Flow §6:
  - [ ] `anomaly` (bool)
  - [ ] `anomaly_type` (enum)
  - [ ] `severity` (float 0.0–1.0)
  - [ ] `confidence` (float 0.0–1.0)
  - [ ] `reasoning` (string ≤300 chars)
  - [ ] `finance_summary` (non-technical)
  - [ ] `engineering_summary` (technical)
  - [ ] `alert_route` (finance / engineering / both)
  - [ ] `suggested_action` (enum)
  - [ ] `dry_run_required` (bool)
  - [ ] `audit_id` (UUID)
- [ ] **Error codes** khớp contract: 400 / 422 / 429 / 503

### ✅ Safety Boundaries — 3 ranh giới đỏ có bị vi phạm không?

- [ ] Gửi request với `environment: "prod"` → engine **KHÔNG bao giờ** trả `suggested_action` = `schedule_shutdown` hay `quota_cap` (chỉ `tag_for_review` hoặc `alert_only`)
- [ ] Module `containment.py` có check cứng: Prod/Staging/Unknown → skip auto-containment
- [ ] Config `FINOPS_NEVER_TERMINATE_PROD`, `FINOPS_NEVER_DELETE_DATA`, `FINOPS_NEVER_MODIFY_IAM` đều default `true` và không có code path nào cho phép override ở runtime

### ✅ Multi-tenant — Có cách ly đúng tenant không?

- [ ] Request thiếu header `X-Tenant-Id` → trả `400`
- [ ] Response header trả lại `X-Tenant-Id` và `X-Correlation-Id`
- [ ] Audit trail log ghi nhận `tenant_id` cho mỗi request
- [ ] Không có shared state giữa các tenant (mỗi request xử lý độc lập)

### ✅ Audit Trail — Log có đủ cho SOC2 không?

- [ ] Mỗi request detect đều sinh `audit_id` (UUID)
- [ ] Audit log ghi: `timestamp`, `tenant_id`, `correlation_id`, `is_anomaly`, `anomaly_type`, `severity`, `confidence`, `reasoning`, `containment_action`, `containment_status`
- [ ] Log dạng structured JSON (CloudWatch Logs đọc được)
- [ ] Config `FINOPS_AUDIT_RETENTION_DAYS=90` (khớp yêu cầu SOC2 ≥90 ngày)

### ✅ Deployment — Chạy được trên ECS Fargate không?

- [ ] Dockerfile chạy trên port `8080`
- [ ] `HEALTHCHECK` endpoint `/health` interval 30s (khớp Deployment Contract)
- [ ] Non-root user (`appuser`) trong container
- [ ] CPU 1024 / Memory 2048 phù hợp requirements
- [ ] Image build thành công: `docker build -t finops-engine .`

### ✅ CDO Integration — CDO gọi được ngay không?

- [ ] CDO dùng curl test: `curl -X POST http://<host>:8080/v1/finops/detect -H "X-Tenant-Id: test-tenant" -H "Content-Type: application/json" -d '{"cost_window": [...]}'` → nhận JSON response hợp lệ
- [ ] CDO dùng curl test health: `curl http://<host>:8080/health` → nhận `{"status": "healthy", ...}`
- [ ] Response schema **không thay đổi** khi AI chuyển từ skeleton sang real logic (W12 T3)

---

## 3. Insight Notes — Những quyết định thiết kế quan trọng

### 3.1 Tại sao dùng Strategy Pattern cho Detection?

```
engine/strategies/
├── base.py           ← Abstract interface (DetectionStrategy)
├── dummy.py          ← W11 skeleton: hardcoded response
└── statistical.py    ← W12: rule-based spike detection
```

**Lý do**: Khi chuyển từ skeleton → real AI, chỉ cần thay đổi **1 dòng config** (`FINOPS_ENABLE_LLM_ANALYSIS=true`). Không cần sửa router, middleware, schema, hay bất kỳ code nào mà CDO depend. Khi curveball yêu cầu thêm thuật toán mới, chỉ cần tạo file strategy mới implement `DetectionStrategy` interface.

### 3.2 Tại sao mọi thứ đều config qua Environment Variables?

**Lý do**: Theo đề bài, curveball có thể yêu cầu:
- Thay đổi threshold phát hiện → sửa `FINOPS_COST_SPIKE_MULTIPLIER`
- Chuyển region → sửa `FINOPS_AWS_REGION`
- Bật/tắt auto-containment → sửa `FINOPS_DRY_RUN_MODE`
- Thay đổi cadence → sửa `FINOPS_DEFAULT_CADENCE_HOURS`

Tất cả đều **không cần build lại Docker image** — chỉ cần update ECS Task Definition → redeploy.

### 3.3 Tại sao tách riêng finance_summary và engineering_summary?

**Lý do**: Đề bài yêu cầu rõ ràng:
- **Finance** đọc dashboard không cần kỹ thuật: *"Chi phí tăng $350/ngày so với trung bình, cần xem xét"*
- **Engineering** cần detail để hành động: *"Account 123456789012 / SageMaker ml.p3.2xlarge / Owner: ml-team — idle since Jun-02"*

Hai summary này phục vụ hai đối tượng khác nhau và được route đến kênh khác nhau (Finance Slack vs Engineering PagerDuty).

### 3.4 Tại sao skeleton có logic phân biệt thay vì luôn trả cùng 1 response?

**Lý do**: Dummy strategy có logic đơn giản: `cost_usd > 200` thì flag anomaly, ngược lại thì normal. Điều này giúp CDO test **cả hai nhánh** của code path:
- **Nhánh anomaly**: Verify alert routing, containment decision, audit trail hoạt động đúng
- **Nhánh normal**: Verify dashboard update, no-action path hoạt động đúng

Nếu luôn trả cùng 1 response, CDO chỉ test được 1 nhánh → thiếu coverage.

### 3.5 Dry-run mode mặc định bật — tại sao?

**Lý do**: Đề bài yêu cầu *"dry-run mode mandatory cho tất cả containment patterns"*. Trong giai đoạn skeleton và đầu W12, mọi containment action chỉ được **mô phỏng** (simulated), không tác động thực lên tài nguyên AWS. Khi team đã test đủ và confident, bật `FINOPS_DRY_RUN_MODE=false` để cho phép thực thi thật trên dev/sandbox.

---

## 4. Mapping Skeleton → Contract Documents

| File trong skeleton | Khớp với Contract/Doc nào | Ghi chú |
|---|---|---|
| `api/schemas/detect.py` → `DetectRequest` | Telemetry Contract §Cost Record Schema + AI API Contract §Request body | Fields: account_id, service, cost_usd, tags, environment, owner, cost_period |
| `api/schemas/detect.py` → `DetectResponse` | AI API Contract §Response body + Operating Flow §6 Response spec | Fields: anomaly, anomaly_type, severity, confidence, reasoning, finance/eng summary, alert_route, audit_id |
| `api/middleware/request_context.py` | AI API Contract §Request headers | Enforce: X-Tenant-Id, X-Correlation-Id |
| `engine/containment.py` | TF2_FINOPS_LEARNER §Hard requirements + Operating Flow §7 | 3 NEVER boundaries + dry-run mandatory |
| `engine/audit.py` | TF2_FINOPS_LEARNER §Audit trail requirement | SOC2: actor, before/after, rollback, retention ≥90 days |
| `engine/alert_router.py` | TF2_FINOPS_LEARNER §Alert routing | Finance vs Engineering routing logic |
| `config/settings.py` | Deployment Contract §Compute + Scale | Port 8080, feature flags, safety boundaries |
| `Dockerfile` | Deployment Contract §Compute + Health check | ECS Fargate, 8080, /health, non-root |

---

## 5. Câu hỏi Review cho Team

Trước khi deploy skeleton lên AWS, mỗi member hãy tự trả lời:

1. **Schema question**: Nếu CDO gửi request với 5 cost items, engine trả response có bao nhiêu anomaly result? *(Trả lời: 1 — engine phân tích cả window và trả 1 kết quả tổng hợp)*
2. **Safety question**: Nếu cost item có `environment: "prod"` và `cost_usd: 10000`, engine có schedule_shutdown không? *(Trả lời: Không — prod luôn bị block, chỉ tag_for_review)*
3. **Integration question**: Khi AI chuyển từ dummy sang real logic ở W12, CDO có cần thay đổi code gì không? *(Trả lời: Không — URL và schema giữ nguyên)*
4. **Audit question**: Làm sao biết request nào từ CDO-01 vs CDO-02? *(Trả lời: Qua header X-Tenant-Id — mỗi CDO platform gửi tenant_id khác nhau)*

---

## 6. Ghi chú vận hành cho CDO

### Cách test skeleton endpoint (CDO dùng lệnh này)

**Test anomaly detection (cost > 200 → anomaly):**
```bash
curl -s -X POST http://<SKELETON_URL>:8080/v1/finops/detect \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: cdo-platform-01" \
  -H "X-Correlation-Id: test-001" \
  -d '{
    "cost_window": [{
      "account_id": "123456789012",
      "service": "Amazon SageMaker",
      "region": "us-east-1",
      "cost_usd": 400.0,
      "usage_type": "ml.p3.2xlarge",
      "tags": {"team": "ml-research"},
      "environment": "dev",
      "cost_period_start": "2026-06-20T00:00:00Z",
      "cost_period_end": "2026-06-21T00:00:00Z"
    }],
    "baseline": {
      "baseline_start": "2026-05-20T00:00:00Z",
      "baseline_end": "2026-06-19T00:00:00Z",
      "baseline_avg_daily_cost_usd": 50.0
    },
    "detection_cadence_hours": 24
  }' | jq .
```

**Test normal spend (cost < 200 → no anomaly):**
```bash
curl -s -X POST http://<SKELETON_URL>:8080/v1/finops/detect \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: cdo-platform-02" \
  -d '{
    "cost_window": [{
      "account_id": "123456789012",
      "service": "Amazon EC2",
      "region": "us-east-1",
      "cost_usd": 30.0,
      "usage_type": "t3.medium",
      "tags": {"team": "backend"},
      "environment": "prod",
      "cost_period_start": "2026-06-20T00:00:00Z",
      "cost_period_end": "2026-06-21T00:00:00Z"
    }],
    "detection_cadence_hours": 24
  }' | jq .
```

**Test health check:**
```bash
curl -s http://<SKELETON_URL>:8080/health | jq .
```

---

## 7. File Map — Mô tả mục đích từng file

> Đọc bảng này để biết nhanh file nào làm gì, thuộc tầng nào, và W12 sẽ thay đổi gì.

### 7.1 Root files (entry point & infra)

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `main.py` | **Entry point** của toàn bộ engine. Khởi tạo FastAPI app, cấu hình structured logging, mount CORS + RequestContextMiddleware, include router, và quản lý lifespan hooks (startup/shutdown). Chạy bằng `uvicorn main:app --port 8080`. | W12: thêm init DB pool, warm ML model cache trong lifespan startup hook. |
| `requirements.txt` | Khai báo Python dependencies (FastAPI, Uvicorn, Pydantic, pydantic-settings, httpx). Pin version cụ thể để đảm bảo reproducible build. | W12: thêm `boto3`, `opentelemetry-*`, `numpy`/`pandas` nếu cần statistical analysis. |
| `Dockerfile` | Multi-stage build image cho ECS Fargate. Base `python:3.12-slim`, non-root user `appuser`, HEALTHCHECK curl `/health` mỗi 30s, expose port 8080, chạy uvicorn 2 workers (phù hợp 1 vCPU). | W12: có thể thêm OTel agent layer hoặc pip install thêm. Không đổi port/healthcheck. |
| `.dockerignore` | Loại bỏ `__pycache__`, tests, `.env`, `.git`, markdown files khỏi Docker context để image nhỏ gọn và không lộ config nhạy cảm. | Không đổi. |
| `.env.example` | Template cho biến môi trường local dev. Liệt kê tất cả `FINOPS_*` env vars với giá trị mặc định an toàn. Copy thành `.env` để chạy local. Production inject qua ECS Task Definition / Secrets Manager. | W12: thêm vars cho Bedrock credentials, DynamoDB table name, OTel endpoint. |
| `SKELETON_CHECKLIST.md` | *File này.* Checklist kiểm tra, insight notes, file map, và workflow cho toàn team review. | Append-only — thêm khi có thay đổi, không xóa nội dung cũ. |

### 7.2 `config/` — Cấu hình ứng dụng

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `config/__init__.py` | Package marker. | — |
| `config/settings.py` | **Toàn bộ cấu hình** engine qua environment variables, dùng `pydantic-settings` để validate + type coerce. Bao gồm: app identity, detection tuning (confidence threshold, cadence, spike multiplier), 3 safety boundaries (`never_terminate_prod`, `never_delete_data`, `never_modify_iam`), feature flags (`enable_llm_analysis`, `dry_run_mode`, `enable_auto_containment`), rate limiting, Bedrock model config, audit retention. Mọi biến có prefix `FINOPS_`. Cached singleton qua `@lru_cache`. | W12: sửa giá trị qua env var, **không cần rebuild image**. Thêm biến mới chỉ cần thêm field vào class Settings. |

### 7.3 `models/` — Domain models & enums

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `models/__init__.py` | Package marker. | — |
| `models/enums.py` | **Từ vựng chung** của toàn engine: `AnomalyType` (runaway_training, idle_resource, mis_tagged_spend, spike_unknown, over_provisioned, other), `AlertRoute` (finance, engineering, both), `SuggestedAction` (alert_only, tag_for_review, schedule_shutdown, quota_cap, investigate), `Environment` (prod, staging, dev, sandbox, unknown), `ContainmentStatus` (dry_run, executed, skipped_prod, escalated, failed). Dùng `str, Enum` để serialize thẳng ra JSON. | W12: thêm enum member khi curveball yêu cầu anomaly type hoặc action mới — chỉ cần thêm 1 dòng. |
| `models/domain.py` | **Internal data structures** engine dùng để reasoning, *tách biệt* khỏi API schema. Gồm: `CostRecord` (dữ liệu chi phí chuẩn hóa từ CDO), `AnomalyResult` (kết quả detection: is_anomaly, type, severity, confidence, reasoning, cost deltas), `ContainmentDecision` (quyết định containment: action, status, dry_run, rollback_path), `AuditEntry` (bản ghi audit trail: audit_id UUID, timestamp, tenant_id, detection_result, containment_decision, actor, before/after state). | W12: có thể thêm fields cho `AnomalyResult` (vd: `root_cause_detail`, `llm_raw_output`). Schema API không bị ảnh hưởng vì tầng này là internal. |

### 7.4 `api/` — HTTP interface layer

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `api/__init__.py` | Package marker. | — |
| `api/router.py` | **Tầng điều phối chính** — định nghĩa 2 endpoints: `GET /health` (health check cho ALB, trả status + version + engine mode + checks) và `POST /v1/finops/detect` (anomaly detection chính). Endpoint detect thực hiện 6 bước tuần tự: (1) extract tenant context từ middleware, (2) chọn & chạy detection strategy, (3) xác định alert routing, (4) đánh giá containment decision, (5) ghi audit trail, (6) build response đúng contract. Strategy selection dựa trên feature flag `enable_llm_analysis`. | W12: **không cần sửa router** khi thêm strategy mới — chỉ sửa `_get_strategy()`. Thêm endpoint mới (vd `/v1/finops/verify`) thì thêm function vào file này. |
| `api/schemas/__init__.py` | Package marker. | — |
| `api/schemas/detect.py` | **Contract schemas** — Pydantic models cho request/response JSON đúng hợp đồng với CDO. Request: `DetectRequest` chứa `cost_window[]` (CostWindowItem: account_id, service, region, cost_usd, usage_type, tags, environment, owner, cost_period), `baseline` (BaselineMetadata), `detection_cadence_hours`, `containment_policy`. Response: `DetectResponse` chứa anomaly, anomaly_type, severity, confidence, reasoning, finance_summary, engineering_summary, alert_route, suggested_action, containment detail, dry_run_required, audit_id, detected_at. Kèm `HealthResponse` cho endpoint `/health`. | W12: **KHÔNG sửa** required fields (contract freeze). Chỉ thêm optional fields mới nếu cần. |
| `api/middleware/__init__.py` | Package marker. | — |
| `api/middleware/request_context.py` | **Cross-cutting middleware** chạy trước mỗi request (trừ `/health`, `/docs`). Trích xuất `X-Tenant-Id` từ header (bắt buộc — trả 400 nếu thiếu), tạo `X-Correlation-Id` nếu CDO không gửi (UUID v4 auto-gen), lưu vào `request.state` cho downstream dùng, gắn cả 2 header vào response, và log request timing (latency ms). | W12: có thể thêm rate limiting check, JWT validation, hoặc OTel span creation tại đây. |

### 7.5 `engine/` — Business logic layer

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `engine/__init__.py` | Package marker. | — |
| `engine/strategies/base.py` | **Abstract Base Class** cho Strategy Pattern. Định nghĩa interface `DetectionStrategy` với method `detect(cost_window, baseline, tenant_id) → AnomalyResult` và property `strategy_name`. Mọi thuật toán detection đều implement ABC này. Swap strategy qua config/feature flag mà không sửa router. | W12: thêm strategy mới (vd `LLMStrategy`, `CompositeStrategy`) chỉ cần tạo file mới implement interface này. |
| `engine/strategies/dummy.py` | **Skeleton strategy** — logic hardcoded phục vụ W11. Rule đơn giản: nếu bất kỳ cost item nào có `cost_usd > 200` thì trả anomaly (runaway_training, severity 0.85, confidence 0.78), ngược lại trả normal. Giúp CDO test cả 2 nhánh code path (anomaly vs normal). Response schema **giống hệt** real engine. | W12: strategy này vẫn giữ lại làm fallback/testing. Chuyển production traffic sang `StatisticalStrategy` hoặc `LLMStrategy`. |
| `engine/strategies/statistical.py` | **Rule-based + statistical strategy** — dùng threshold từ config (`cost_spike_multiplier`, default 2.0x). So sánh tổng cost window vs baseline avg daily cost. Nếu ratio ≥ multiplier → anomaly. Phân loại anomaly type bằng heuristic: service chứa "sagemaker"/"training" → runaway_training, >50% items thiếu tags → mis_tagged_spend, chỉ có dev/sandbox envs → idle_resource. Severity và confidence tính từ ratio. | W12: thay heuristic bằng ML model (IsolationForest, Z-Score), thêm per-service baseline profiling, kết nối CUR data store thật. |
| `engine/strategies/__init__.py` | Re-export `DummyStrategy` và `StatisticalStrategy` cho import tiện. | W12: thêm export strategy mới. |
| `engine/alert_router.py` | **Phân tuyến alert** tới Finance, Engineering, hoặc cả hai. Rules: severity ≥ 0.7 → both; runaway_training/idle_resource/over_provisioned → engineering; mis_tagged_spend/spike_unknown → both; other → finance. Kèm 2 hàm tạo summary: `generate_finance_summary()` (không kỹ thuật: "$X/ngày, vượt baseline Y%") và `generate_engineering_summary()` (chi tiết: account, service, severity, confidence, delta). | W12: có thể thêm LLM-generated summaries thay thế template strings. Routing rules mở rộng theo curveball. |
| `engine/containment.py` | **Quyết định ngăn chặn an toàn** — module quan trọng nhất về safety. Enforces 3 HARD BOUNDARIES ở code level. Decision tree: (1) không anomaly → alert_only/skipped, (2) prod/staging/unknown → tag_for_review chỉ (TUYỆT ĐỐI không auto-act), (3) non-prod + confidence thấp → investigate/escalate, (4) non-prod + confidence cao → action phù hợp (schedule_shutdown, quota_cap, tag_for_review) qua dry-run trước. Action map: runaway_training → schedule_shutdown, idle_resource → schedule_shutdown, mis_tagged_spend → tag_for_review, over_provisioned → quota_cap. Kèm rollback path cho mỗi action. | W12: bật `enable_auto_containment=true` + `dry_run_mode=false` để thực thi trên dev/sandbox thật. Prod boundaries **KHÔNG BAO GIỜ** bị tắt. |
| `engine/audit.py` | **Audit trail logger** — ghi bản ghi bất biến cho mỗi detection + containment decision. SOC2 yêu cầu: actor, before/after state, rollback path, retention ≥ 90 ngày. Skeleton: log structured JSON ra stdout (CloudWatch Logs capture). `AuditLogger` class tạo `AuditEntry` với UUID audit_id, ghi timestamp, tenant_id, correlation_id, anomaly details, containment action/status. Module-level singleton `audit_logger`. | W12: swap `_persist()` method sang DynamoDB writer (pk=tenant_id, sk=audit_id) + S3 archive, không sửa caller code nào. |

### 7.6 `tests/` — Test suite

| File | Mục đích | Ghi chú W12 |
|---|---|---|
| `tests/__init__.py` | Package marker. | — |
| `tests/test_detect.py` | **Integration + contract tests** cho endpoint `POST /v1/finops/detect` và `GET /health`. Verify: (1) health check trả 200 + đúng schema, (2) anomaly case (cost > 200) trả đúng response fields, (3) normal case trả anomaly=false, (4) missing X-Tenant-Id trả 400, (5) prod environment trả suggested_action an toàn (không schedule_shutdown/quota_cap). Dùng FastAPI TestClient (httpx). | W12: thêm test cho statistical strategy, LLM strategy mock, containment policy scenarios, rate limiting, và audit trail verification. |

---

## 8. Request Lifecycle Workflow

> Đây là luồng xử lý **chi tiết** khi CDO gửi request đến skeleton. Mọi member đọc để hiểu data đi qua những module nào.

### 8.1 Toàn cảnh — từ CDO request đến CDO nhận response

```text
CDO Platform
    │
    │  POST /v1/finops/detect
    │  Headers: X-Tenant-Id, X-Correlation-Id (optional)
    │  Body: { cost_window: [...], baseline: {...}, detection_cadence_hours: 24 }
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  main.py — FastAPI Application (port 8080)                                │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  MIDDLEWARE: api/middleware/request_context.py                       │  │
│  │                                                                      │  │
│  │  1. Kiểm tra X-Tenant-Id header                                     │  │
│  │     ├─► Thiếu ──► return 400 { "error": "missing_tenant_id" }       │  │
│  │     └─► Có    ──► tiếp tục                                          │  │
│  │                                                                      │  │
│  │  2. X-Correlation-Id                                                 │  │
│  │     ├─► Có    ──► dùng giá trị CDO gửi                              │  │
│  │     └─► Thiếu ──► auto-generate UUID v4                             │  │
│  │                                                                      │  │
│  │  3. Lưu tenant_id + correlation_id vào request.state                │  │
│  │  4. Bắt đầu đo thời gian request (latency)                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  ROUTER: api/router.py — POST /v1/finops/detect                     │  │
│  │                                                                      │  │
│  │  Bước 1: Extract tenant context từ request.state                    │  │
│  │                                                                      │  │
│  │  Bước 2: DETECTION — chọn strategy theo feature flag                │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │  _get_strategy()                                               │  │  │
│  │  │  ├─ FINOPS_ENABLE_LLM_ANALYSIS=false ──► DummyStrategy         │  │  │
│  │  │  └─ FINOPS_ENABLE_LLM_ANALYSIS=true  ──► StatisticalStrategy   │  │  │
│  │  │                                                                 │  │  │
│  │  │  strategy.detect(cost_window, baseline, tenant_id)              │  │  │
│  │  │                      │                                          │  │  │
│  │  │                      ▼                                          │  │  │
│  │  │               AnomalyResult                                     │  │  │
│  │  │  { is_anomaly, anomaly_type, severity, confidence, reasoning,  │  │  │
│  │  │    baseline_cost, current_cost, delta_usd, delta_pct }          │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                       │  │
│  │  Bước 3: ALERT ROUTING                                              │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │  engine/alert_router.py                                        │  │  │
│  │  │                                                                 │  │  │
│  │  │  determine_alert_route(result)                                  │  │  │
│  │  │  ├─ severity >= 0.7           ──► BOTH                          │  │  │
│  │  │  ├─ runaway/idle/overprov     ──► ENGINEERING                   │  │  │
│  │  │  ├─ mis_tagged/spike_unknown  ──► BOTH                          │  │  │
│  │  │  └─ other / no anomaly        ──► FINANCE                       │  │  │
│  │  │                                                                 │  │  │
│  │  │  generate_finance_summary(result)                               │  │  │
│  │  │  ──► "Chi phí $X/ngày, vượt baseline $Y (+Z%)"                 │  │  │
│  │  │                                                                 │  │  │
│  │  │  generate_engineering_summary(result)                           │  │  │
│  │  │  ──► "Account: 123... | Service: SageMaker | Delta: +$350"      │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                       │  │
│  │  Bước 4: CONTAINMENT EVALUATION                                     │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │  engine/containment.py                                         │  │  │
│  │  │                                                                 │  │  │
│  │  │  evaluate_containment(result, resource_env, policy, tenant_id)  │  │  │
│  │  │                                                                 │  │  │
│  │  │  Decision tree:                                                 │  │  │
│  │  │  ├─ Không anomaly?         ──► ALERT_ONLY / SKIPPED            │  │  │
│  │  │  ├─ Env = prod/staging?    ──► TAG_FOR_REVIEW / SKIPPED_PROD   │  │  │
│  │  │  │   🚫 TUYỆT ĐỐI KHÔNG auto-act trên prod                    │  │  │
│  │  │  ├─ Confidence < 0.6?      ──► INVESTIGATE / ESCALATED         │  │  │
│  │  │  └─ Non-prod + cao conf?   ──► Action phù hợp + DRY_RUN       │  │  │
│  │  │       ├─ runaway_training  ──► schedule_shutdown                │  │  │
│  │  │       ├─ idle_resource     ──► schedule_shutdown                │  │  │
│  │  │       ├─ mis_tagged_spend  ──► tag_for_review                   │  │  │
│  │  │       └─ over_provisioned  ──► quota_cap                        │  │  │
│  │  │                                                                 │  │  │
│  │  │  Output: ContainmentDecision                                    │  │  │
│  │  │  { action, status, target_env, dry_run_required,                │  │  │
│  │  │    dry_run_passed, rollback_path }                              │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                       │  │
│  │  Bước 5: AUDIT TRAIL                                                │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │  engine/audit.py                                               │  │  │
│  │  │                                                                 │  │  │
│  │  │  audit_logger.create_audit_entry(                               │  │  │
│  │  │      tenant_id, correlation_id,                                 │  │  │
│  │  │      detection_result, containment_decision                     │  │  │
│  │  │  )                                                              │  │  │
│  │  │                                                                 │  │  │
│  │  │  ──► Sinh UUID audit_id                                         │  │  │
│  │  │  ──► Ghi structured JSON log ra stdout                          │  │  │
│  │  │      (CloudWatch Logs capture, retention >= 90 ngày)            │  │  │
│  │  │  ──► Return AuditEntry { audit_id, timestamp, ... }             │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  │                              │                                       │  │
│  │  Bước 6: BUILD RESPONSE                                             │  │
│  │  ┌────────────────────────────────────────────────────────────────┐  │  │
│  │  │  Ghép tất cả kết quả thành DetectResponse:                     │  │  │
│  │  │  {                                                              │  │  │
│  │  │    "anomaly": true/false,                                       │  │  │
│  │  │    "anomaly_type": "runaway_training",                          │  │  │
│  │  │    "severity": 0.85,                                            │  │  │
│  │  │    "confidence": 0.78,                                          │  │  │
│  │  │    "reasoning": "...",                                           │  │  │
│  │  │    "finance_summary": "Chi phí $400/ngày...",                   │  │  │
│  │  │    "engineering_summary": "Account 123... | SageMaker...",      │  │  │
│  │  │    "alert_route": "both",                                       │  │  │
│  │  │    "suggested_action": "schedule_shutdown",                      │  │  │
│  │  │    "containment": { action, target, dry_run, rollback },        │  │  │
│  │  │    "dry_run_required": true,                                    │  │  │
│  │  │    "audit_id": "uuid-...",                                       │  │  │
│  │  │    "detected_at": "2026-06-23T10:30:00Z"                        │  │  │
│  │  │  }                                                              │  │  │
│  │  └────────────────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  MIDDLEWARE (response phase)                                        │  │
│  │  ──► Gắn header X-Correlation-Id + X-Tenant-Id vào response        │  │
│  │  ──► Log: latency_ms, tenant, status code                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
    │
    │  HTTP 200 + JSON response
    │
    ▼
CDO Platform
    ├──► Route alert tới Finance Slack / Engineering PagerDuty
    ├──► Cập nhật Dashboard (spend trend + anomaly overlay)
    └──► Lưu audit_id để tra cứu sau
```

### 8.2 Health Check Workflow

```text
ALB / CDO / Monitoring
    │
    │  GET /health  (không cần X-Tenant-Id)
    │
    ▼
┌───────────────────────────────────────────┐
│  Middleware: SKIP (path /health exempt)    │
└───────────────────────────┬───────────────┘
                            ▼
┌───────────────────────────────────────────┐
│  Router: health_check()                   │
│                                           │
│  ──► Load settings (version, env)         │
│  ──► Get current strategy name            │
│  ──► Return:                              │
│      {                                    │
│        "status": "healthy",               │
│        "version": "0.1.0-skeleton",       │
│        "environment": "development",      │
│        "engine_mode": "dummy_skeleton",   │
│        "checks": {                        │
│          "config_loaded": "ok",           │
│          "detection_strategy": "dummy..", │
│          "dry_run_mode": "enabled",       │
│          "auto_containment": "disabled"   │
│        }                                  │
│      }                                    │
└───────────────────────────────────────────┘
    │
    │  HTTP 200
    ▼
ALB marks target healthy (2 consecutive 200)
```

### 8.3 Error Flows

```text
Flow A — Missing X-Tenant-Id:
  CDO ──► POST /v1/finops/detect (no X-Tenant-Id header)
       ──► Middleware ──► return 400 { "error": "missing_tenant_id" }
       ──► CDO phải sửa code, KHÔNG retry

Flow B — Invalid request body (Pydantic validation fail):
  CDO ──► POST /v1/finops/detect (cost_window rỗng hoặc sai type)
       ──► FastAPI auto-validate ──► return 422 { "detail": [...validation errors...] }
       ──► CDO sửa payload

Flow C — Engine internal error:
  CDO ──► POST /v1/finops/detect
       ──► Strategy.detect() throw exception
       ──► Router catch ──► return 503 { "detail": "AI engine detection failed" }
       ──► CDO fallback sang rule-based alert (BẮT BUỘC có fallback path)
```

### 8.4 Luồng dữ liệu tổng hợp — Ai gọi ai

```text
config/settings.py ◄──────────────── mọi module đều đọc config
        │
        ▼
models/enums.py ◄──────────────────── từ vựng chung cho toàn engine
        │
        ▼
models/domain.py ◄─────────────────── data structures nội bộ
        │
        ▼
api/schemas/detect.py ◄───────────── contract schemas (request/response)
        │                                      ▲
        │                                      │
        ▼                                      │
api/middleware/request_context.py               │
        │                                      │
        ▼                                      │
api/router.py ─────► engine/strategies/*.py     │
        │                    │                  │
        │                    ▼                  │
        ├──────────► engine/alert_router.py     │
        │                                      │
        ├──────────► engine/containment.py      │
        │                                      │
        ├──────────► engine/audit.py            │
        │                                      │
        └──────────► Build DetectResponse ──────┘
```

---

*Cập nhật file này khi có thay đổi. Append-only — không xóa nội dung cũ.*
