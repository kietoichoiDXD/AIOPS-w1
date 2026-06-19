# Changelog — 6 Acceptance Scenarios

## Tổng quan

Lab đã được mở rộng từ **3 kịch bản cơ bản** lên **6 kịch bản toàn diện** để kiểm tra orchestrator ở các tình huống thực tế phức tạp hơn.

---

## Kịch bản đã có (1-3)

### Scenario 1 — Action succeeds
- Kiểm tra flow cơ bản: Detect → Decide → Dry-run → Act → Verify → Success
- Alert: HighLatency trên payment-svc
- Expected: ACTION_SUCCESS

### Scenario 2 — Action fails → rollback
- Kiểm tra cơ chế rollback tự động
- Alert: InstanceDown trên checkout-svc
- Expected: ROLLBACK_TRIGGERED và ROLLBACK_EXECUTED

### Scenario 3 — Circuit breaker
- Kiểm tra circuit breaker sau 3 lần thất bại liên tiếp
- Expected: CIRCUIT_BREAKER_HALT sau failure thứ 3

---

## Kịch bản mới (4-6)

### Scenario 4 — Blast-radius limit exceeded ✨ MỚI
**Mục tiêu**: Kiểm tra enforcement của rate limiting (blast-radius)

**Kỹ thuật**:
- Cấu hình `max_actions_per_minute: 2`
- Inject fault trên 3 service khác nhau trong vòng 60 giây
- Alert 1 và 2: thực thi thành công
- Alert 3: bị reject với log `BLAST_RADIUS_EXCEEDED`

**Observable outcomes**:
- Log shows `BLAST_RADIUS_OK` (x2) → `BLAST_RADIUS_EXCEEDED`
- Không có `RUNBOOK_EXEC` cho alert thứ 3
- Prometheus gauge `closed_loop_blast_radius_remaining`: 2 → 1 → 0
- Action: escalate (không tự động thực thi)

**Lý do quan trọng**: Trong production, blast-radius limit ngăn orchestrator gây thundering herd khi có cascade failure. Scenario này đảm bảo orchestrator tuân thủ giới hạn và không vượt quá.

---

### Scenario 5 — Cascading failure recovery ✨ MỚI
**Mục tiêu**: Kiểm tra xử lý cascade failure (upstream service down → downstream errors)

**Kỹ thuật**:
- Kill api-gateway (upstream service)
- Downstream services (payment-svc, inventory-svc) fire `HighErrorRate` alerts
- Orchestrator phải xử lý root cause trước (api-gateway)
- Downstream services tự recover sau khi upstream hồi phục

**Observable outcomes**:
- Log sequence: `ALERT_DETECTED` (api-gateway) → `ACTION_SUCCESS` → `ALERT_DETECTED` (downstream)
- Downstream alerts có thể auto-resolve sau khi upstream fix
- Per-service mutex đảm bảo không có restart redundant
- Không có circular restart loops

**Lý do quan trọng**: Cascade failure là pattern phổ biến trong microservices. Orchestrator phải detect root cause và tránh waste action trên downstream services đã auto-recover.

---

### Scenario 6 — Verify timeout and recovery ✨ MỚI
**Mục tiêu**: Kiểm tra resilience của verify polling strategy với timing edge cases

**Kỹ thuật**:
- Cấu hình `verify_timeout_seconds: 30`, `verify_min_samples: 3`
- Inject latency → action executes → manually recover sau 10 giây
- Verify đang poll, service recover giữa các poll samples
- Orchestrator phải yêu cầu 3 consecutive passing samples

**Observable outcomes**:
- Log shows multiple `VERIFY_POLLING` events
- Early polls có thể fail (metric > threshold)
- Later polls pass (metric < threshold)
- `VERIFY_PASS` xuất hiện chỉ sau khi có 3 consecutive passes
- Không có false positive từ 1 sample may mắn

**Lý do quan trọng**: Trong production, service recovery không tức thời — metric có thể spike rồi ổn định. Verify strategy phải robust với timing: không declare success quá sớm (false positive) và không timeout quá nhanh (false negative).

---

## Cập nhật Rubric

Rubric đã được mở rộng từ **6 criteria** lên **8 criteria**:

| Criterion mới | Điểm tối đa | Nội dung |
|---|---|---|
| 6. Blast-radius enforcement | 5 | Refuses actions khi limit reached + logs BLAST_RADIUS_EXCEEDED + gauge accurate |
| 7. Cascading failure handling | 5 | Prioritizes root cause + skips redundant actions + downstream auto-resolves |
| 8. Verify resilience | 5 | Configurable poll interval + min_samples + handles mid-verify recovery + timeout protection |

**Scoring thresholds**:
- Passing (scenarios 1-3): ≥ 12/25 (criteria 1-5)
- Good (scenarios 1-4): ≥ 18/30 (criteria 1-6)
- Excellent (scenarios 1-6): ≥ 30/40 (all 8 criteria)

---

## Stress Tests (optional, scenarios 7-9)

Ba kịch bản nâng cao vẫn được giữ lại trong `expected.json` cho advanced learners:

- **Scenario 7**: Multi-step transactional rollback
- **Scenario 8**: Concurrent alert race (per-service mutex)
- **Scenario 9**: LLM hallucination defense (decision validation)

---

## File đã cập nhật

1. **HANDOUT.md**:
   - Section 5: Expanded from 3 → 6 scenarios
   - Section 6: Rubric updated (6 → 8 criteria)
   - References to "3 chaos scenarios" → "6 chaos scenarios"

2. **README.md**:
   - Pack inventory: noted "6 acceptance scenarios"
   - Scripts: added "recover" command documentation

3. **data/expected.json**:
   - Added `scenario_4_blast_radius`
   - Added `scenario_5_cascading_failure`
   - Added `scenario_6_verify_timeout`
   - Renamed old stress tests: scenario_4 → scenario_7, etc.

---

## Hướng dẫn sử dụng

### Để chạy 6 kịch bản chính:

```bash
# Scenario 1-3: như cũ
bash data-pack/scripts/inject_fault.sh latency payment-svc 500ms
bash data-pack/scripts/inject_fault.sh kill checkout-svc
# ... (xem HANDOUT.md)

# Scenario 4: Blast-radius
# Sửa config.yaml: max_actions_per_minute: 2
bash data-pack/scripts/inject_fault.sh latency payment-svc 500ms
sleep 5
bash data-pack/scripts/inject_fault.sh latency inventory-svc 500ms
sleep 5
bash data-pack/scripts/inject_fault.sh latency checkout-svc 500ms

# Scenario 5: Cascading failure
bash data-pack/scripts/inject_fault.sh kill api-gateway
# Đợi 30s để xem downstream alerts

# Scenario 6: Verify timeout
bash data-pack/scripts/inject_fault.sh latency payment-svc 500ms
sleep 10
bash data-pack/scripts/inject_fault.sh recover payment-svc
```

### Config cần thiết

Trong `config.yaml`, đảm bảo có:

```yaml
blast_radius:
  max_actions_per_minute: 3  # Giảm xuống 2 cho scenario 4

verify_thresholds:
  latency_p99_max_ms: 500
  up_required: 1

verify_timeout_seconds: 60    # Giảm xuống 30 cho scenario 6
verify_poll_interval_seconds: 10
verify_min_samples: 3
```

---

## Tác động lên implementation

Để pass scenarios 4-6, orchestrator cần implement:

1. **Blast-radius guard** (scenario 4):
   - Track actions per minute window
   - Refuse execution khi exceed limit
   - Log `BLAST_RADIUS_EXCEEDED` với action=escalate

2. **Alert prioritization** (scenario 5):
   - KHÔNG cần priority queue phức tạp
   - Chỉ cần per-service mutex (serialize same service)
   - Process alerts theo thứ tự detect
   - Downstream tự resolve sau upstream fix

3. **Verify polling với min_samples** (scenario 6):
   - Poll Prometheus multiple times trong verify_timeout
   - Track consecutive passing samples
   - Require `verify_min_samples` passes trước khi VERIFY_PASS
   - Handle partial failures (1 fail giữa các pass → reset counter)

---

## Kết luận

Mở rộng từ 3 → 6 scenarios mang lại:

✅ **Coverage tốt hơn**: Test các edge cases thực tế (rate limiting, cascade, timing)  
✅ **Rubric rõ ràng hơn**: 8 criteria chi tiết với scoring thresholds  
✅ **Defense mạnh hơn**: Sinh viên phải lý giải lựa chọn design cho từng tình huống  
✅ **Production-ready**: Orchestrator pass 6 scenarios có thể handle production workload thực tế  

Lab vẫn giữ nguyên spirit: build working orchestrator, not simulation. Tất cả 6 scenarios chạy trên stack thực với Prometheus/Alertmanager thật.

