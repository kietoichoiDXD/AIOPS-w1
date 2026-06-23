# Hợp đồng Đo lường Chi phí (Telemetry Contract) - Task Force 2 (FinOps Watch)

<!-- Owner: Nhóm AI 2
     Signed by: AI Lead + CDO Leads × 2 + Reviewer panel
     Date signed: 2026-06-25 (W11 T5)
     🔒 FREEZE - Không thay đổi nếu không có yêu cầu thay đổi chính thức (Formal Change Request) -->

## 1. Mục đích

Hợp đồng này định nghĩa **các tín hiệu (signals) dữ liệu chi phí** mà nhóm CDO (Cloud/DevOps) phải thu thập (PULL) từ hạ tầng AWS để cung cấp cho AI Engine của nhóm AI. Đây là thỏa thuận giao tiếp (handshake) giữa tầng nền tảng (CDO Platform Layer) và tầng trí tuệ nhân tạo (AI Engine Layer) nhằm phục vụ việc phát hiện các chi tiêu bất thường (anomaly detection).

Khác với các hệ thống telemetry truyền thống (gửi metrics thời gian thực theo giây), dữ liệu chi phí trong FinOps được trích xuất theo chu kỳ (batch-oriented PULL) do đặc thù cập nhật dữ liệu của AWS.

---

## 2. Quản lý phiên bản (Versioning)

- **Phiên bản hiện tại**: `v1.0`
- **Nguyên tắc phát triển**: Chỉ thực hiện các thay đổi tương thích ngược (backward-compatible). Các thay đổi phá vỡ cấu trúc (breaking changes) bắt buộc phải tạo phiên bản hợp đồng mới và có khoảng thời gian chuyển đổi (migration window).
- **Quy trình thay đổi**: Yêu cầu thay đổi được thảo luận công khai trong Task Force -> Thống nhất phương án -> Cập nhật phiên bản hợp đồng -> Triển khai nâng cấp đồng bộ.

---

## 3. Các tín hiệu yêu cầu (Signals Required)

Nhóm AI yêu cầu hai nguồn dữ liệu chi phí chính sau từ nhóm CDO:

### 3.1. Signal 1: `aws_cur_line_items` (AWS Cost & Usage Report 2.0)

Chi tiết sử dụng tài nguyên ở mức độ thấp (granular resource-level). Đây là nguồn thông tin chính xác nhất để phát hiện các bất thường như tài nguyên bị bỏ quên (runaway/idle resources) và tài nguyên không được gắn thẻ (untagged spend).

| Thuộc tính (Attribute) | Giá trị (Value) |
|---|---|
| **Kiểu tín hiệu (Type)** | Dữ liệu dạng bảng (CSV/Parquet) / Batch Event |
| **Các cột bắt buộc (Fields/Labels)** | `line_item_usage_start_date`, `line_item_usage_account_id`, `line_item_usage_account_name`, `line_item_product_code`, `line_item_usage_type`, `line_item_operation`, `line_item_resource_id`, `line_item_unblended_cost`, `resource_tags_user_team`, `resource_tags_user_environment` |
| **Đơn vị (Unit)** | USD (Cost) / Số lượng sử dụng (Usage amount) |
| **Tần suất (Frequency)** | PULL mỗi 12 giờ hoặc 24 giờ (khớp với tần suất AWS ghi dữ liệu CUR vào S3) |
| **Nguồn phát sinh (Emit Point)** | AWS CUR 2.0 S3 Bucket -> AWS Athena / CDO Ingestion Pipeline -> AI Engine |
| **Thời gian lưu trữ (Retention)** | Tối thiểu 90 ngày (để phục vụ backtest và lưu vết kiểm toán/audit trail) |
| **Mục đích sử dụng** | Phát hiện bất thường ở mức chi tiết (resource-level anomalies), định danh đội ngũ chịu trách nhiệm (`team` tag), và đề xuất hành động ngăn chặn (containment actions) |
| **SLA Freshness** | Dữ liệu được nạp vào AI Engine trong vòng 1 giờ kể từ khi AWS cập nhật CUR trên S3 |

**Ví dụ dữ liệu JSON gửi sang AI Engine**:
```json
{
  "line_item_usage_start_date": "2026-06-25T00:00:00Z",
  "line_item_usage_account_id": "123456789012",
  "line_item_usage_account_name": "ml-research",
  "line_item_product_code": "AmazonEC2",
  "line_item_usage_type": "BoxUsage:p3.2xlarge",
  "line_item_operation": "RunInstances",
  "line_item_resource_id": "i-0abcd1234efgh5678",
  "line_item_unblended_cost": 73.44,
  "line_item_usage_amount": 24.0,
  "pricing_unit": "Hrs",
  "product_region_code": "us-east-1",
  "resource_tags_user_team": "squad-ml-core",
  "resource_tags_user_environment": "dev",
  "resource_tags_user_cost_center": "cc-102",
  "resource_tags_user_owner": "researcher-dev@company.com"
}
```

---

### 3.2. Signal 2: `aws_cost_explorer_daily` (AWS Cost Explorer API)

Dữ liệu chi phí tổng hợp hàng ngày theo tài khoản và dịch vụ. Được sử dụng để nhanh chóng phát hiện các đột biến chi phí tổng thể (sudden spikes) hoặc sự tăng trưởng chi phí chậm nhưng kéo dài (gradual drift).

| Thuộc tính (Attribute) | Giá trị (Value) |
|---|---|
| **Kiểu tín hiệu (Type)** | Dữ liệu tổng hợp (Daily Aggregate) |
| **Các cột bắt buộc (Fields/Labels)** | `date`, `linked_account_id`, `linked_account_name`, `service`, `service_code`, `region`, `unblended_cost`, `is_estimated` |
| **Đơn vị (Unit)** | USD |
| **Tần suất (Frequency)** | PULL mỗi 12 giờ hoặc 24 giờ |
| **Nguồn phát sinh (Emit Point)** | AWS Cost Explorer API (`get-cost-and-usage`) -> CDO Collector -> AI Engine |
| **Thời gian lưu trữ (Retention)** | Tối thiểu 90 ngày |
| **Mục đích sử dụng** | Phát hiện nhanh các bất thường mức độ tổng hợp (aggregate-level anomalies) và đối chiếu nhanh không qua truy vấn Athena |
| **SLA Freshness** | Dữ liệu được nạp vào AI Engine trong vòng 30 phút kể từ khi CDO thực hiện gọi API |

**Ví dụ dữ liệu JSON gửi sang AI Engine**:
```json
{
  "date": "2026-06-25",
  "linked_account_id": "123456789012",
  "linked_account_name": "staging",
  "service": "Amazon Elastic Compute Cloud - Compute",
  "service_code": "AmazonEC2",
  "region": "us-east-1",
  "unblended_cost": 420.50,
  "is_estimated": false
}
```

---

## 4. Yêu cầu kỹ thuật chung (Cross-cutting Requirements)

Mọi tín hiệu dữ liệu chi phí được cung cấp phải tuân thủ các nguyên tắc sau:

1. **Phân bổ theo tài khoản (Account-scoping)**: Mọi dòng dữ liệu bắt buộc phải có thông tin tài khoản liên kết (`linked_account_id` hoặc `line_item_usage_account_id`) làm cơ sở định danh tenant.
2. **Xử lý dữ liệu ước tính (Estimated vs Final)**: Dữ liệu của 2 ngày gần nhất thường ở trạng thái ước tính (`is_estimated = true`). Nhóm CDO phải gắn cờ này để AI Engine xử lý đặc biệt (tránh báo động giả do dữ liệu chưa đồng bộ hoàn toàn).
3. **Độ chính xác thời gian**: Tất cả thời gian sử dụng phải được định dạng theo tiêu chuẩn RFC3339 UTC.
4. **Không chứa thông tin nhạy cảm (PII)**: Nhóm CDO phải lọc bỏ hoặc ẩn danh các dữ liệu nhạy cảm của khách hàng trong các tag tài nguyên trước khi chuyển sang AI Engine. Chỉ cho phép giữ lại tag `owner` (email định danh) để phục vụ việc định tuyến cảnh báo (alert routing).
5. **Xử lý thẻ trống (Empty Tags)**: Các tài nguyên thiếu tag bắt buộc (`team`, `environment`) phải được giữ nguyên giá trị trống hoặc gán nhãn `untagged` để AI Engine phân loại lỗi gắn thẻ.

---

## 5. Câu hỏi mở (Open Questions)

- [ ] **Q1**: Làm thế nào để CDO xử lý lỗi rate-limiting khi gọi AWS Cost Explorer API nếu tần suất kiểm tra tăng lên (ví dụ: chạy ad-hoc)?
- [ ] **Q2**: Trong trường hợp AWS xuất CUR muộn (đôi khi trễ tới 12 tiếng), CDO có cần phát ra một tín hiệu cảnh báo trễ dữ liệu (`telemetry_delay_event`) để AI Engine tạm dừng suy luận hay không?
