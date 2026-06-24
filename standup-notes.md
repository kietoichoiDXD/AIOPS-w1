# Standup Notes — Task Force 2 (FinOps Watch)

## Quy tắc ghi chép (Strict Rules)
- Daily Standup lúc 14h00 hàng ngày, thời lượng giới hạn 15 phút.
- Ghi chép dạng append-only, KHÔNG xóa lịch sử cũ.
- Format cho mỗi thành viên:
  - **Done**: Việc đã hoàn thành trong 24h qua.
  - **Doing**: Việc sẽ làm trong 24h tới.
  - **Blocker**: Rào cản kỹ thuật/nghiệp vụ đang gặp phải.

---

## 2026-06-22 (Tuần 11 - Thứ 2)
- **Cohort Kickoff & Đề tài**: Nhóm AI bốc thăm bốc trúng đề tài **Task Force 2 (FinOps Watch)**.
- **Client Interview**: Phỏng vấn mentor-as-Client làm rõ các ranh giới đỏ (Prod, data deletion, IAM), success criteria (Precision >= 80%, FP <= 10%), và ngân sách Bedrock (<$50/tháng).
- **Ghi chú**: Bắt đầu nghiên cứu dữ liệu lịch sử CUR và Cost Explorer trong `data/tf2-finops`.

## 2026-06-23 (Tuần 11 - Thứ 3)
- **AI Team**:
  - **Done**: Thiết lập cấu trúc thư mục làm việc, viết nháp ADR-001 (Hybrid Architecture) và ADR-002 (Ingestion Cadence). Phác thảo cấu trúc Telemetry Contract.
  - **Doing**: Phác thảo cấu trúc API Contract và Deployment Contract.
  - **Blocker**: Chưa làm rõ cơ chế can thiệp an toàn ở các môi trường trung gian.
- **CDO Team**:
  - **Done**: Review cấu trúc VPC base và cluster ECS.
  - **Doing**: Viết base IaC Terraform.
  - **Blocker**: Chờ đặc tả API của nhóm AI để thiết kế mock endpoints.

## 2026-06-24 (Tuần 11 - Thứ 4)
- **AI Team**:
  - **Done**: 
    - Hoàn thành bản thảo `telemetry-contract.md` (JSON Schema cho Cost Explorer, CUR, CloudWatch).
    - Hoàn thành bản thảo `deployment-contract.md` (CodeDeploy Blue/Green, ECS Fargate scale).
    - Hoàn thành bản thảo `ai-api-contract.md` với mô hình 6 endpoints và cơ chế Async Detection + Polling.
    - Viết code FastAPI Skeleton Engine (`api/main.py`) và Dockerfile cho early integration.
  - **Doing**: Phối hợp với nhóm CDO rà soát các hợp đồng chéo (Co-design).
  - **Blocker**: Không có.
- **CDO Team**:
  - **Done**: Hoàn thành base VPC IaC và ECS Cluster Terraform.
  - **Doing**: Review 3 bản thảo hợp đồng do nhóm AI công bố, chuẩn bị nội dung push-back/thảo luận cho sáng Thứ 5.
  - **Blocker**: Không có.
