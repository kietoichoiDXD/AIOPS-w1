# SUBMIT.md — Kết quả chạy các kịch bản Closed-Loop Auto-Remediation

## Thông tin chung

- **Tác giả:** Kiet (`kietoichoiDXD`)
- **Decision Engine:** Rule-based (Ánh xạ `runbook_map` trong `config.yaml`)
- **Môi trường chạy:** Python 3.12 (uv), Docker Compose v2, Windows 11 (Git Bash cho runbook execution)
- **Cấu hình chốt chặn:**
  - **Blast Radius:** Tối đa 3 action/phút; 5 restarts/service/giờ.
  - **Verify step:** Kiểm tra latency p99 (< 500ms) và service status (`up` == 1), yêu cầu 3 sample liên tiếp.
  - **Circuit Breaker:** Ngắt tự động sau 3 lần verify thất bại liên tiếp (Manual reset).
  - **Stress Extensions:** Per-service Mutex lock (đa luồng), Transactional Multi-step Deploy & Rollback, LLM Hallucination Defense.

---

## 1. Scenario 1 — Action thành công (HighLatency trên payment-svc)

**Thiết lập:** Gửi cảnh báo giả lập `HighLatency` cho service `payment-svc` khi hệ thống đang chạy bình thường dưới traffic nền.

**Log của orchestrator:**
```json
{"ts": "2026-06-19T05:47:29.859108+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-19T05:47:29.859169+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-19T05:47:29.859191+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}
{"ts": "2026-06-19T05:47:29.859326+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": true}
{"ts": "2026-06-19T05:47:29.929778+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-payment-svc", "stderr": ""}
{"ts": "2026-06-19T05:47:29.929840+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-19T05:47:29.930122+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
{"ts": "2026-06-19T05:47:37.867405+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-payment-svc...\nronki-payment-svc\n[restart_service] Waiting 5s for ronki-payment-svc to come up...\n[restart_service] ronki-payment-svc is running.", "stderr": ""}
{"ts": "2026-06-19T05:47:37.867639+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-19T05:47:37.867778+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "payment-svc", "timeout_s": 60}
{"ts": "2026-06-19T05:47:37.887103+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 1, "latency_p99_ms": 248.30263157894737, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-19T05:47:47.909591+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 2, "latency_p99_ms": 248.14285714285714, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-19T05:47:57.953426+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 3, "latency_p99_ms": 248.17391304347828, "up": 1.0, "latency_ok": true, "up_ok": true}
{"ts": "2026-06-19T05:47:57.953519+00:00", "level": "INFO", "event_type": "VERIFY_PASS", "service": "payment-svc", "samples": 3}
{"ts": "2026-06-19T05:47:57.953632+00:00", "level": "INFO", "event_type": "ACTION_SUCCESS", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
```

**Kết quả:** PASS. Orchestrator phát hiện alert, chạy thử dry-run thành công, sau đó chạy thực tế restart service. Bước verify ghi nhận 3 sample latency ổn định ở mức 248ms (nhỏ hơn ngưỡng 500ms) và ghi nhận khắc phục thành công (`ACTION_SUCCESS`).

---

## 2. Scenario 2 — Verify thất bại & Kích hoạt Auto-Rollback

**Thiết lập:** Để kiểm thử rollback, hạ ngưỡng `latency_p99_max_ms` xuống `1` trong `baseline.json` và gửi alert `HighLatency` cho `payment-svc`.

**Log của orchestrator:**
```json
{"ts": "2026-06-19T05:51:23.659462+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-19T05:51:23.659640+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-19T05:51:23.659694+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}
{"ts": "2026-06-19T05:51:23.659916+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": true}
{"ts": "2026-06-19T05:51:23.768512+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-payment-svc", "stderr": ""}
{"ts": "2026-06-19T05:51:23.768716+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-19T05:51:23.768918+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
{"ts": "2026-06-19T05:51:31.533664+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-payment-svc...\nronki-payment-svc\n[restart_service] Waiting 5s for ronki-payment-svc to come up...\n[restart_service] ronki-payment-svc is running.", "stderr": ""}
{"ts": "2026-06-19T05:51:31.533763+00:00", "level": "INFO", "event_type": "ACTION_EXECUTED", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-19T05:51:31.533854+00:00", "level": "INFO", "event_type": "VERIFY_START", "service": "payment-svc", "timeout_s": 60}
{"ts": "2026-06-19T05:51:31.554605+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 1, "latency_p99_ms": 248.1546762589928, "up": 0.0, "latency_ok": false, "up_ok": false}
{"ts": "2026-06-19T05:51:41.583563+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 2, "latency_p99_ms": 248.16666666666669, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-19T05:51:51.616661+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 3, "latency_p99_ms": 248.21942446043164, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-19T05:52:01.633115+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 4, "latency_p99_ms": 248.1934306569343, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-19T05:52:11.658881+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 5, "latency_p99_ms": 248.16666666666666, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-19T05:52:21.685741+00:00", "level": "INFO", "event_type": "VERIFY_SAMPLE", "service": "payment-svc", "sample": 6, "latency_p99_ms": 248.2062937062937, "up": 1.0, "latency_ok": false, "up_ok": true}
{"ts": "2026-06-19T05:52:31.686373+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "payment-svc", "samples": 6}
{"ts": "2026-06-19T05:52:31.686604+00:00", "level": "WARNING", "event_type": "ROLLBACK_TRIGGERED", "service": "payment-svc", "rollback_runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-19T05:52:31.686742+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
{"ts": "2026-06-19T05:52:39.791430+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[restart_service] Restarting ronki-payment-svc...\nronki-payment-svc\n[restart_service] Waiting 5s for ronki-payment-svc to come up...\n[restart_service] ronki-payment-svc is running.", "stderr": ""}
{"ts": "2026-06-19T05:52:39.791490+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "payment-svc", "rollback_runbook": "runbooks/restart_service.sh"}
```

**Kết quả:** PASS. Vì latency thực tế (248ms) > ngưỡng mock (1ms), bước verify liên tục báo `latency_ok: false`. Sau khi hết thời gian timeout (60 giây), orchestrator phát hiện verify thất bại (`VERIFY_FAIL`), tự động kích hoạt rollback runbook (`ROLLBACK_TRIGGERED`) và hoàn thành việc khôi phục (`ROLLBACK_EXECUTED`).

---

## 3. Scenario 3 — Circuit Breaker (3 lần thất bại liên tiếp)

**Thiết lập:** Duy trì ngưỡng latency tối đa là 1ms. Gửi tiếp các alert `HighLatency` cho `inventory-svc` và `checkout-svc` để tạo chuỗi 3 lần thất bại liên tiếp.

**Log của orchestrator:**
```json
[Lần thất bại thứ 1 - payment-svc]
{"ts": "2026-06-19T05:52:31.686373+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "payment-svc", "samples": 6}
{"ts": "2026-06-19T05:52:39.791490+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "payment-svc", "rollback_runbook": "runbooks/restart_service.sh"}

[Lần thất bại thứ 2 - inventory-svc]
{"ts": "2026-06-19T05:53:39.835878+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "inventory-svc"}
...
{"ts": "2026-06-19T05:54:47.730814+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "inventory-svc", "samples": 6}
{"ts": "2026-06-19T05:54:55.636419+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "inventory-svc", "rollback_runbook": "runbooks/restart_service.sh"}

[Lần thất bại thứ 3 - checkout-svc]
{"ts": "2026-06-19T05:54:55.636593+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "checkout-svc"}
...
{"ts": "2026-06-19T05:56:03.897979+00:00", "level": "WARNING", "event_type": "VERIFY_FAIL", "service": "checkout-svc", "samples": 6}
{"ts": "2026-06-19T05:56:11.619483+00:00", "level": "INFO", "event_type": "ROLLBACK_EXECUTED", "service": "checkout-svc", "rollback_runbook": "runbooks/restart_service.sh"}

[Mạch bảo vệ ngắt (Trip)]
{"ts": "2026-06-19T05:56:11.619513+00:00", "level": "ERROR", "event_type": "CIRCUIT_BREAKER_HALT", "consecutive_failures": 3, "threshold": 3, "message": "Automation halted. Manual intervention required."}
```

**Kết quả:** PASS. Khi số lượng lỗi liên tiếp đạt ngưỡng `3`, Circuit Breaker chuyển sang trạng thái `OPEN`. Orchestrator dừng việc poll Alertmanager, phát sự kiện `CIRCUIT_BREAKER_HALT` và yêu cầu người vận hành can thiệp thủ công.

---

## 4. Scenario 4 — Transactional Multi-step Deploy & Rollback

**Thiết lập:** Khởi động lại CB, khôi phục ngưỡng latency về 500ms. Sửa đổi tạm thời step C của runbook `multi_step_deploy.sh` để giả lập lỗi (`exit 1` cho `api-gateway`). Gửi alert `HighDeploymentError` cho `api-gateway`.

**Log của orchestrator:**
```json
{"ts": "2026-06-19T06:10:49.742900+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighDeploymentError", "service": "api-gateway", "severity": "warning"}
{"ts": "2026-06-19T06:10:49.742997+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighDeploymentError", "service": "api-gateway", "runbook": "runbooks/multi_step_deploy.sh"}
{"ts": "2026-06-19T06:10:49.743049+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "api-gateway"}
{"ts": "2026-06-19T06:10:49.743289+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh", "service": "api-gateway", "dry_run": true}
{"ts": "2026-06-19T06:10:49.849174+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/multi_step_deploy.sh", "service": "api-gateway"}

[Thực thi các bước tuần tự A -> B -> C]
{"ts": "2026-06-19T06:10:49.849393+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-a", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-19T06:10:52.038182+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-a", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] step-A: draining traffic from ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] step-A complete."}
{"ts": "2026-06-19T06:10:52.038458+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-b", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-19T06:10:57.961067+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-b", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] step-B: applying new config to ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] step-B complete."}
{"ts": "2026-06-19T06:10:57.961586+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-19T06:10:58.171814+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "returncode": 1, "stdout": "[multi_step_deploy] step-C: re-enabling traffic for ronki-api-gateway...\n[multi_step_deploy] MOCK FAILURE for api-gateway in step-C"}

[Phát hiện lỗi ở step C và Rollback ngược: B -> A]
{"ts": "2026-06-19T06:10:58.172042+00:00", "level": "ERROR", "event_type": "TRANSACTIONAL_STEP_FAIL", "step": "runbooks/multi_step_deploy.sh --step-c", "service": "api-gateway", "completed_before_failure": ["runbooks/multi_step_deploy.sh --step-a", "runbooks/multi_step_deploy.sh --step-b"]}
{"ts": "2026-06-19T06:10:58.172142+00:00", "level": "WARNING", "event_type": "TRANSACTIONAL_ROLLBACK_STEP", "step": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway"}
{"ts": "2026-06-19T06:10:58.172357+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-19T06:11:05.535797+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --rollback-b", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] rollback-B: reverting config on ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] rollback-B complete."}
{"ts": "2026-06-19T06:11:05.536061+00:00", "level": "WARNING", "event_type": "TRANSACTIONAL_ROLLBACK_STEP", "step": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway"}
{"ts": "2026-06-19T06:11:05.536307+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway", "dry_run": false}
{"ts": "2026-06-19T06:11:08.937567+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/multi_step_deploy.sh --rollback-a", "service": "api-gateway", "returncode": 0, "stdout": "[multi_step_deploy] rollback-A: restoring traffic to ronki-api-gateway...\nronki-api-gateway\n[multi_step_deploy] rollback-A complete."}
{"ts": "2026-06-19T06:11:08.937790+00:00", "level": "INFO", "event_type": "TRANSACTIONAL_ROLLBACK_COMPLETE", "service": "api-gateway", "rolled_back": ["runbooks/multi_step_deploy.sh --rollback-b", "runbooks/multi_step_deploy.sh --rollback-a"]}
```

**Kết quả:** PASS. Orchestrator thực thi các bước A và B thành công. Khi bước C gặp lỗi, orchestrator lập tức phát hiện giao dịch lỗi và kích hoạt quy trình rollback ngược (rollback step B rồi mới rollback step A), không tiến hành rollback step C do nó chưa hoàn thành.

---

## 5. Scenario 5 — Per-service Mutex Lock (Xử lý đa luồng)

**Thiết lập:** Chuyển đổi orchestrator sang chạy đa luồng (`threading.Thread`). Gửi đồng thời hai cảnh báo khác nhau (`HighLatency` và `HighErrorRate`) cho cùng dịch vụ `payment-svc`.

**Log của orchestrator:**
```json
{"ts": "2026-06-19T06:27:16.329975+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighLatency", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-19T06:27:16.330126+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighLatency", "service": "payment-svc", "runbook": "runbooks/restart_service.sh"}
{"ts": "2026-06-19T06:27:16.330164+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}
{"ts": "2026-06-19T06:27:16.330271+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "HighErrorRate", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-19T06:27:16.330300+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": true}
{"ts": "2026-06-19T06:27:16.330344+00:00", "level": "INFO", "event_type": "DECIDE_RUNBOOK", "alertname": "HighErrorRate", "service": "payment-svc", "runbook": "runbooks/clear_cache.sh"}
{"ts": "2026-06-19T06:27:16.330492+00:00", "level": "INFO", "event_type": "BLAST_RADIUS_OK", "service": "payment-svc"}

[Mutex lock từ chối cảnh báo thứ hai]
{"ts": "2026-06-19T06:27:16.330637+00:00", "level": "WARNING", "event_type": "SERVICE_LOCK_BUSY", "service": "payment-svc", "message": "Another runbook is executing for this service; skipping duplicate"}

{"ts": "2026-06-19T06:27:16.402979+00:00", "level": "INFO", "event_type": "RUNBOOK_RESULT", "script": "runbooks/restart_service.sh", "service": "payment-svc", "returncode": 0, "stdout": "[DRY-RUN] would execute: docker restart ronki-payment-svc", "stderr": ""}
{"ts": "2026-06-19T06:27:16.403049+00:00", "level": "INFO", "event_type": "DRY_RUN_PASS", "runbook": "runbooks/restart_service.sh", "service": "payment-svc"}
{"ts": "2026-06-19T06:27:16.403207+00:00", "level": "INFO", "event_type": "RUNBOOK_EXEC", "script": "runbooks/restart_service.sh", "service": "payment-svc", "dry_run": false}
```

**Kết quả:** PASS. Khi cả hai alert cùng đi vào xử lý song song, luồng xử lý `HighLatency` giành được lock trước. Luồng xử lý `HighErrorRate` cố gắng tranh chấp lock nhưng thất bại, lập tức báo `SERVICE_LOCK_BUSY` và bỏ qua để tránh hành động thừa đè lên nhau.

---

## 6. Scenario 6 — Hallucination Defense (Decision Validation)

**Thiết lập:** Thêm cấu hình alert name giả lập `TestHallucination` trỏ tới runbook ảo giác `"runbooks/hallucinated_runbook.sh"`, nhưng KHÔNG thêm runbook này vào whitelist `runbook_registry`. Gửi alert `TestHallucination`.

**Log của orchestrator:**
```json
{"ts": "2026-06-19T06:27:50.832160+00:00", "level": "INFO", "event_type": "ALERT_DETECTED", "alertname": "TestHallucination", "service": "payment-svc", "severity": "warning"}
{"ts": "2026-06-19T06:27:50.832322+00:00", "level": "ERROR", "event_type": "DECISION_VALIDATION_FAILED", "bad_runbook": "runbooks/hallucinated_runbook.sh", "alertname": "TestHallucination", "raw_decision": "runbooks/hallucinated_runbook.sh", "action": "escalate_no_auto_action"}
```

**Kết quả:** PASS. Orchestrator phát hiện runbook quyết định không nằm trong whitelist đăng ký trước, ghi nhận lỗi `DECISION_VALIDATION_FAILED` và lập tức dừng thực thi (`escalate_no_auto_action`), tránh việc chạy các câu lệnh không rõ nguồn gốc.

---

## Những bài học đúc kết

1. **Ý nghĩa của Đa luồng (Multi-threading):** Trong phiên bản ban đầu, orchestrator chạy tuần tự khiến Mutex Lock không bao giờ bị tranh chấp thực sự trên local. Việc chuyển đổi vòng lặp xử lý sang đa luồng giúp hệ thống vừa phản ứng nhanh với các sự cố độc lập vừa cô lập được hành động khắc phục một cách đồng thời.
2. **Rollback tuần tự ngược:** Việc áp dụng thứ tự LIFO (Last-In-First-Out) trong rollback giao dịch (như tắt traffic trước khi khôi phục config) giúp bảo vệ hệ thống khỏi việc nhận tải khi chưa sẵn sàng.
3. **Chốt chặn whitelist:** Cơ chế Hallucination Defense là tối quan trọng khi tích hợp LLM làm Decision Engine, vì các mô hình ngôn ngữ lớn rất dễ sinh ra các câu lệnh ảo giác có thể gây sập hệ thống nếu không có whitelist chặt chẽ.
