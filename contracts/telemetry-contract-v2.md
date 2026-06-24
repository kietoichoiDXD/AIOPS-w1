# Hợp đồng Đo lường Chi phí (Telemetry Contract) - Phiên bản v2.0 - Task Force 2 (FinOps Watch)

<!-- Owner: Nhóm AI
     Signed by: AI Lead + CDO Leads × 2 + Reviewer panel
     Date signed: 2026-06-25 (W11 T5)
     🔒 FREEZE - Không thay đổi nếu không có yêu cầu thay đổi chính thức (Formal Change Request) -->

## 1. Mục đích và Các nâng cấp cốt lõi (Purpose & Core Upgrades v2.0)

Hợp đồng Telemetry Phiên bản v2.0 được nâng cấp nhằm giải quyết các hạn chế về độ trễ dữ liệu (Data Latency) và tăng khả năng drill-down phân tích lãng phí ở cấp độ Container/Kubernetes. 

### Các điểm nâng cấp chính so với v1.0:
1. **Giảm độ trễ phát hiện (MTTD) từ 12h xuống < 15 phút**: Bổ sung tín hiệu thời gian thực từ **AWS CloudTrail Event Bridge** để phát hiện ngay lập tức các hành động "đốt tiền" (như bật instance GPU khủng P3/P4 hoặc tạo RDS instance lớn) thay vì đợi AWS xuất CUR (8-12 tiếng).
2. **Hỗ trợ phân tích EKS/K8s Over-provisioning**: Bổ sung tín hiệu hiệu năng Container (CPU/Memory Request vs Limit) để phát hiện lãng phí do cấu hình thừa thãi.
3. **Chuẩn hóa Payload JSON v2.0**: Tổ chức lại cấu trúc dữ liệu dạng lồng (nested) giúp tối ưu dung lượng payload truyền qua API `POST /v2/detect` tới 40%.

---

## 2. Quản lý phiên bản và Lộ trình chuyển đổi (Versioning & Migration)

- **Phiên bản hiện tại**: `v2.0` (Đồng bộ với `/v2/` của AI API Contract).
- **Hỗ trợ song song (Dual-run Window)**: Hệ thống AI Engine sẽ hỗ trợ song song cả API v1.0 và v2.0 trong vòng **30 ngày** kể từ ngày ký kết. Nhóm CDO phải hoàn thành chuyển đổi pipeline thu thập trước ngày 2026-07-25.

---

## 3. Danh mục các Tín hiệu v2.0 (v2.0 Signals Specification)

### 3.1. Signal 1: `daily_cur_spend_usd_v2` (AWS CUR 2.0 Parquet Stream)

Dữ liệu chi tiết sử dụng tài nguyên được CDO tối ưu hóa bằng cách chuyển đổi sang định dạng Parquet trên S3 và nạp dạng micro-batch mỗi 6 giờ.

| Thuộc tính (Attribute) | Giá trị (Value) |
|---|---|
| **Kiểu tín hiệu (Type)** | Dữ liệu dạng bảng (Parquet) nạp qua `POST /v2/detect` |
| **Tần suất (Frequency)** | PULL mỗi 6 giờ |
| **Nguồn phát sinh (Source)** | AWS CUR 2.0 S3 -> Athena Parquet Export -> AI Engine |

**Cấu trúc JSON Payload v2.0 (Nested Structure)**:
```json
{
  "ts": "2026-06-22T00:00:00Z",
  "signal_name": "daily_cur_spend_usd_v2",
  "value": 420.00,
  "labels": {
    "resource": {
      "id": "arn:aws:sagemaker:ap-southeast-1:123456789012:notebook-instance/notebook-instance-training-v2",
      "type": "SageMaker-Notebook",
      "region": "ap-southeast-1",
      "service": "SageMaker"
    },
    "cost": {
      "unblended_rate": 17.50,
      "unblended_cost": 420.00,
      "currency": "USD",
      "billing_period_start": "2026-06-01T00:00:00Z"
    },
    "usage": {
      "amount": 24.0,
      "unit": "Hrs",
      "operation": "RunInstances",
      "usage_type": "BoxUsage:p3.2xlarge"
    },
    "tags": {
      "team": "squad-ml-core",
      "environment": "dev",
      "cost_center": "CC-1002",
      "owner": "researcher-dev@company.com"
    }
  }
}
```

---

### 3.2. Signal 2: `aws_cloudtrail_event` (Real-time Provisioning Event) - [NEW v2.0]

Tín hiệu sự kiện thay đổi hạ tầng từ AWS CloudTrail. Giúp AI Engine bắt được các hành động "đốt tiền" (như bật instance GPU khủng P3/P4 hoặc tạo RDS instance lớn) gần như ngay lập tức.

| Thuộc tính (Attribute) | Giá trị (Value) |
|---|---|
| **Kiểu tín hiệu (Type)** | Real-time Event (JSON) |
| **Tần suất (Frequency)** | PUSH ngay khi sự kiện xảy ra (Streaming qua EventBridge) |
| **Nguồn phát sinh (Source)** | AWS CloudTrail -> EventBridge Rule -> CDO Ingestion -> AI Engine |
| **Mục đích sử dụng** | Rút ngắn MTTD xuống < 15 phút cho các vụ sudden spike do con người tạo mới tài nguyên. |

**Cấu trúc JSON Payload gửi sang AI Engine**:
```json
{
  "ts": "2026-06-22T10:15:30Z",
  "signal_name": "aws_cloudtrail_event",
  "value": 1.0,
  "labels": {
    "event_name": "RunInstances",
    "event_source": "ec2.amazonaws.com",
    "aws_region": "us-east-1",
    "user_identity": "arn:aws:iam::123456789012:user/developer-05",
    "request_parameters": {
      "instance_type": "p3.8xlarge",
      "image_id": "ami-0abcd1234efgh5678",
      "min_count": 2,
      "max_count": 2
    },
    "resource_tags": {
      "team": "squad-training-model",
      "environment": "dev"
    }
  }
}
```

---

### 3.3. Signal 3: `eks_container_resource_metrics` (Kubernetes Over-provisioning) - [NEW v2.0]

Tín hiệu đo lường hiệu năng Container chạy trong cụm EKS, dùng để phát hiện lãng phí do các đội dev đăng ký tài nguyên (Request) quá lớn nhưng sử dụng thực tế (Usage) quá thấp.

| Thuộc tính (Attribute) | Giá trị (Value) |
|---|---|
| **Kiểu tín hiệu (Type)** | Hiệu năng Container (CPU/Memory ratio) |
| **Tần suất (Frequency)** | Thu thập mỗi 1 giờ |
| **Nguồn phát sinh (Source)** | Prometheus (Metric server) -> CDO Collector -> AI Engine |

**Cấu trúc JSON Payload gửi sang AI Engine**:
```json
{
  "ts": "2026-06-22T11:00:00Z",
  "signal_name": "eks_container_resource_metrics",
  "value": 0.08, -- Tỷ lệ sử dụng thực tế / Request (8%)
  "labels": {
    "cluster_name": "tf2-production-cluster",
    "namespace": "squad-payment",
    "pod_name": "payment-api-6f78d9b-abc12",
    "container_name": "payment-gateway",
    "metrics": {
      "cpu_request_cores": 4.0,
      "cpu_usage_cores": 0.32,
      "memory_request_bytes": 8589934592, -- 8 GB
      "memory_usage_bytes": 1073741824 -- 1 GB
    }
  }
}
```

---

## 4. Đặc tả API Endpoint v2.0 và SLA bổ sung

*   **Endpoint nhận dữ liệu**: `POST /v2/detect`
*   **SLA Latency**: P99 Latency < 40ms đối với dữ liệu CloudTrail event và < 150ms đối với micro-batch Parquet data (do kích thước payload v2.0 tối ưu).
*   **Cơ chế Idempotency v2.0**: Khóa idempotency bắt buộc cấu trúc:
    `[tenant_id]_[billing_period_YYYYMMDD]_[batch_sequence_id]_[api_version_v2]` để tránh xung đột chéo dữ liệu với phiên bản v1.0.

---

## 5. Quy trình phục hồi khi mất dữ liệu Telemetry v2.0

* **Mất luồng CloudTrail streaming**: Hệ thống tự động chuyển sang cơ chế giám sát chu kỳ batch (CUR/Cost Explorer) và phát cảnh báo cảnh báo giảm tốc độ phát hiện bất thường của hệ thống.
* **Mất luồng EKS metrics**: Hệ thống tạm dừng đưa ra các đề xuất Right-sizing/Over-provisioning cho cụm EKS đó, đảm bảo không có hành động containment sai lệch nào được thực hiện trên Kubernetes.
