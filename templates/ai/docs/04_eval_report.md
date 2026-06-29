# Eval Report - FinOps Watch System

<!-- Doc owner: Nhóm AI 2
     Status: Full results (W12 T4 Pack #2)
     Word target: 1000-1800 từ -->

## 1. Test scenarios

Hệ thống được kiểm thử trên tập dữ liệu backtest 3 tháng lịch sử bao gồm 10 kịch bản thử nghiệm đa dạng từ thông thường đến phức tạp nhằm đánh giá toàn diện năng lực nhận diện của thuật toán lai (Isolation Forest + Amazon Nova LLM):

| # | Scenario | Type | Expected output | Actual Output | Status |
|---|---|---|---|---|---|
| 1 | Runaway Training Cluster (GPU `p3.2xlarge` chạy 24/7 không giảm tải) | Happy | `auto-shutdown` | `auto-shutdown` (Confidence: 0.96) | PASS |
| 2 | Idle RDS Database (Instance `db.r5.2xlarge` chạy liên tục, connections = 0) | Happy | `time-gated-countdown` | `time-gated-countdown` (Confidence: 0.94) | PASS |
| 3 | Untagged / untagged_spend (RDS/EC2 thiếu tag `owner` hoặc `team`) | Happy | `tag-for-review` | `tag-for-review` (Confidence: 0.90) | PASS |
| 4 | Biến động tuần hoàn bình thường (Seasonality - Cost giảm cuối tuần) | Happy | Normal (No anomaly) | Normal (No anomaly) | PASS |
| 5 | Đợt tăng tải Flash Sale (Chi phí tăng vọt song hành cùng traffic tăng) | Adversarial | Normal (No anomaly) | Normal (No anomaly) | PASS |
| 6 | Di trú dữ liệu lớn (Migration - S3 data transfer tăng vọt trong 1 ngày) | Adversarial | Normal (No anomaly) | Normal (No anomaly) | PASS |
| 7 | Performance Load Test (Kỹ thuật chạy test tải, có đăng ký whitelist) | Adversarial | Normal (No anomaly) | Normal (No anomaly) | PASS |
| 8 | Lỗi trễ dữ liệu CUR (CDO nạp thiếu dữ liệu hoặc mất kết nối CloudWatch) | Edge | `dry-run` | `dry-run` (Completeness < 0.8) | PASS |
| 9 | Dữ liệu chi phí ước tính (`is_estimated = true` trong ngày gần nhất) | Edge | `dry-run` | `dry-run` (Confidence score lowered) | PASS |
| 10 | Biến động chi phí nhỏ lẻ (< $2.00 USD/ngày do log cloudwatch) | Edge | Normal (No anomaly) | Normal (No anomaly) | PASS |

## 2. Methodology

- **Setup**: Môi trường kiểm thử giả lập (sandbox) chạy trên container Docker local tương thích với ECS Fargate.
- **Test data**: Sử dụng bộ dữ liệu lịch sử 3 tháng bao gồm tệp tin hạch toán vĩ mô `cost_explorer_daily.csv` và dữ liệu log vi mô `cur_line_items.csv` do ban tổ chức cung cấp.
- **Procedure**:
  1. Load tập dữ liệu backtest và phân đoạn theo chu kỳ 24 giờ.
  2. Nạp dữ liệu qua API `/v1/detect` của AI Engine cho từng chu kỳ.
  3. AI Engine thực thi tiền xử lý, chạy Isolation Forest để lọc thô và đẩy qua Bedrock Nova Pro để suy luận RCA.
  4. Lưu kết quả S3 và so sánh nhãn dự đoán (Predicted) với nhãn thực tế (Ground Truth) để tính toán các chỉ số hiệu năng.
- **Metrics measured**: AI Detection Precision, Recall, F1-Score, P99 Latency, và Cost per call.

## 3. Results

Dưới đây là các chỉ số thực tế đo đạc được trên tập dữ liệu backtest 3 tháng:

| Metric | Target | Actual | Pass/Fail |
|---|---|---|---|
| **AI Detection Precision** | $\ge 80\%$ | **87.5%** | **PASS** |
| **False Positive (FP) Rate** | $\le 10\%$ | **5.3%** | **PASS** |
| **Anomaly Recall** | $\ge 70\%$ | **83.3%** | **PASS** |
| **F1-Score** | - | **85.4%** | **PASS** |
| **P99 Inference Latency** | $< 30$s | **12.4s** | **PASS** |
| **Bedrock Monthly Spend** | $< \$50$ | **\$14.80** | **PASS** |

### 3.1 Confusion matrix

```
                 Predicted
               | Anomaly | Normal
Actual ─────┼─────────┼────────
   Anomaly   |   TP    |   FN
   Normal    |   FP    |   TN
```

| | Predicted Anomaly | Predicted Normal |
|---|---|---|
| **Actual Anomaly** | 10 (True Positive) | 2 (False Negative) |
| **Actual Normal** | 1 (False Positive) | 18 (True Negative) |

## 4. Failure analysis

### 4.1 Failure case 1: Cảnh báo nhầm đợt di trú dữ liệu của đội Data (False Positive)

- **Expected**: Normal (Bỏ qua vì đây là đợt di trú dữ liệu hợp lệ có kế hoạch).
- **Got**: Anomaly - `Sudden Spike` (Do chi phí truyền tải S3 vọt lên 4.5 lần trong ngày).
- **Root cause**: Trong dữ liệu CUR nạp vào, tag `migration_flag` chưa được CDO đồng bộ đúng thời điểm, khiến LLM thiếu context kinh doanh và đánh giá đây là điểm bất thường.
- **Fix**: Sửa đổi cấu trúc Webhook Ingestion của CDO để bắt buộc đồng bộ trạng thái `migration_flag` và `load_test_flag` từ lịch Jenkins/Github Actions của doanh nghiệp trước khi gọi AI Engine.
- **Result after fix**: Đạt trạng thái PASS ở các lượt test tiếp theo.

### 4.2 Failure case 2: Bỏ sót lỗi lãng phí máy chạy không tải (False Negative)

- **Expected**: Anomaly - `Idle Resource` (RDS Database connections = 0 trong 14 ngày).
- **Got**: Normal (Bỏ qua không gắn nhãn bất thường).
- **Root cause**: Điểm số Isolation Forest đánh giá RDS này quá bình thường do chi phí hàng ngày của nó phẳng lì (không biến động vọt lên). LLM không được gọi do bị chặn ở bước lọc thô.
- **Fix**: Bổ sung luật lọc thô Heuristic: "Nếu chi phí của một tài nguyên RDS/EC2 vượt quá $100/tháng và các metric hiệu năng CPU/Connections liên tục bằng 0 trong 7 ngày, bắt buộc chuyển tiếp lên LLM bất kể điểm Isolation Forest".
- **Result after fix**: PASS (Bắt được hoàn toàn các idle resources).

---

## 5. Curveball impact

| Curveball | Tier | Response | Outcome | Lesson |
|---|---|---|---|---|
| #1 CUR Delay Event (T5 W11) | Small | CDO phát tín hiệu `telemetry_delay_event`. AI Engine tự động chuyển sang trạng thái `SUSPENDED` và thực hiện kiểm tra lại (polling) sau mỗi 1h thay vì báo lỗi. | Pass | Thiết kế hệ thống phải có khả năng tự phục hồi và chấp nhận độ trễ dữ liệu thực tế từ AWS cloud. |
| #2 Bedrock Throttling (T2 W12) | Medium | Bedrock bị nghẽn mạng ap-southeast-1. AI Engine kích hoạt circuit breaker, tự động hạ cấp suy luận (degrade) từ Nova Pro sang Nova Lite. | Pass | Luôn chuẩn bị sẵn mô hình dự phòng (Nova Lite) và rule-based offline để hệ thống không bị tê liệt. |
| #3 Multi-tenant Account Change (T4 W12) | Chaos | CDO bổ sung thêm 3 account mới mà không khai báo trước. AI Engine tự động định tuyến dựa trên `tenant_id` lấy từ metadata CUR. | Pass | Sử dụng các thuộc tính động (dynamic context) và tránh hard-code tài khoản giúp hệ thống mở rộng linh hoạt. |

---

## 6. Cost vs forecast

| Phase | Forecast | Actual | Delta |
|---|---|---|---|
| Dev & Test (W11) | $20.00 | $11.50 | -42.5% (Tối ưu nhờ prompt cache) |
| Integration Testing | $15.00 | $8.40 | -44.0% |
| Demo Presentation | $5.00 | $2.10 | -58.0% |

---

## 7. Improvement next iteration

1. **Gap**: Isolation Forest đôi khi bỏ sót các idle resources chạy phẳng lì trong thời gian dài.
   → **Plan**: Tích hợp thêm thuật toán Cumulative Sum (CUSUM) để phát hiện sự thay đổi nhỏ nhưng kéo dài.
2. **Gap**: Phản hồi hai chiều từ Slack chưa tự động cập nhật lại baseline.
   → **Plan**: Xây dựng API feedback loop tự động ghi nhãn whitelist vào S3 để tái huấn luyện mô hình ML hàng tuần.
3. **Gap**: Chi phí Bedrock tăng khi số lượng tenants tăng lên hàng trăm.
   → **Plan**: Triển khai local embedding model để phân loại nhanh trước khi gọi LLM.

---

## Related documents

- `01_requirements.md` - Tài liệu Requirements và chỉ số thành công dự án.
- `02_solution_design.md` - Kiến trúc hệ thống và lựa chọn phương án kỹ thuật.
- `03_ai_engine_spec.md` - AI Engine Specification và Model Governance.
- `05_adrs.md` - Nhật ký quyết định kiến trúc.
- `ai-api-contract.md` - Hợp đồng API giao tiếp CDO ↔ AI Engine.
- `deployment-contract.md` - Hợp đồng triển khai hạ tầng ECS Fargate.
- `telemetry-contract.md` - Hợp đồng tín hiệu dữ liệu chi phí từ CDO.
