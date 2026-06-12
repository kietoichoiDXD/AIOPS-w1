# BÁO CÁO KẾT QUẢ - TÁI THIẾT KẾ OBSERVABILITY STACK

## 1. Kết luận ngắn

Tôi đề xuất chuyển GeekShop từ stack phân mảnh sang một kiến trúc chuẩn hóa dựa trên OpenTelemetry + Grafana LGTM.

Mục tiêu:
- giảm chi phí từ `$42,000/tháng` xuống dưới `$25,200/tháng`
- giảm MTTR ít nhất `30%`
- không làm mất khả năng phản ứng sự cố
- có migration từng bước với rollback trong vòng dưới 30 phút

## 2. Điểm mấu chốt của thiết kế

- OTel Collector là điểm kiểm soát ingest duy nhất
- tail-based sampling giữ trace quan trọng, thay vì head-based sampling 1%
- drop label ở edge để chặn cardinality explosion
- Mimir nhận metrics, Loki nhận logs, Tempo nhận traces
- Alertmanager route sang PagerDuty và Slack
- Grafana là UI hợp nhất để giảm context switching

## 3. Công cụ vẽ sơ đồ

Hai thư viện phù hợp nhất:
- `Mermaid` để nhúng trực tiếp trong Markdown/GitHub
- `Graphviz` để render sơ đồ phức tạp thành PNG/SVG đẹp hơn

## 4. Ý nghĩa kiến trúc

Thiết kế này không cắt giảm capability. Nó:
- gom observability về một control plane
- giảm chi phí storage/search ở logs
- cải thiện khả năng truy nguyên sự cố nhờ traces đầy đủ hơn
- giữ PagerDuty vì alert routing là phần khó thay nhất

