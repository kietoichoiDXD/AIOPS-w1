# FINDINGS - GeekShop Observability Redesign

## 1. Tóm tắt

Thiết kế mới chuyển GeekShop từ stack observability phân mảnh sang một đường ống chuẩn hóa dựa trên OpenTelemetry và Grafana LGTM.

Mục tiêu đạt được:
- giảm chi phí quan sát từ `$42,000/tháng` xuống dưới `$25,200/tháng`
- giảm MTTR trung vị ít nhất `30%`
- giữ nguyên hoặc cải thiện khả năng phản ứng sự cố
- có lộ trình migration nhiều giai đoạn với rollback rõ ràng

Kiến trúc tôi chọn:
- OpenTelemetry SDK + OTel Collector ở edge
- Grafana Mimir cho metrics
- Grafana Loki cho logs
- Grafana Tempo cho traces
- Grafana Alertmanager để route alert sang PagerDuty và Slack
- Grafana Unified UI làm một giao diện duy nhất cho on-call

Nguồn nghiên cứu chính:
- [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
- [OpenTelemetry Sampling](https://opentelemetry.io/docs/concepts/sampling/)
- [Tail sampling](https://opentelemetry.io/docs/languages/dotnet/traces/tail-based-sampling/)
- [Grafana Cloud](https://grafana.com/docs/grafana-cloud/)
- [Grafana Loki](https://grafana.com/docs/loki/latest/)
- [Grafana Tempo](https://grafana.com/docs/tempo/latest/)
- [Grafana pricing](https://grafana.com/pricing/)
- [Mermaid flowchart syntax](https://mermaid.js.org/syntax/flowchart.html)
- [Graphviz documentation](https://graphviz.org/documentation/)

## 2. Cách tôi giải bài

Tôi dùng đúng khung kiến trúc:
- yêu cầu -> trade-off -> ADR -> migration -> rủi ro -> POC

Tôi ưu tiên những quyết định sau:
- chuẩn hóa ingestion bằng OTel Collector
- chuyển query surface sang Grafana LGTM
- giữ PagerDuty vì alert routing là phần khó thay nhất
- dùng tail-based sampling thay vì head-based sampling 1%
- drop label ở edge để khống chế cardinality

## 3. Lựa chọn công cụ vẽ

Tôi đề xuất dùng:
- `Mermaid` cho sơ đồ kiến trúc trong Markdown vì dễ review trên GitHub
- `Graphviz` khi cần layout DOT chặt hơn hoặc render PNG/SVG cho báo cáo

Lý do:
- Mermaid dễ nhúng trực tiếp vào repo
- Graphviz mạnh hơn cho graph phức tạp và xuất ảnh đẹp
- cả hai đều có tài liệu chính thức, dễ tái tạo trong CI

## 4. Kết luận kỹ thuật

Thiết kế này không cố "cắt chi phí bằng cách tắt observability". Thay vào đó, nó:
- giảm duplication giữa Datadog, Splunk, PagerDuty, Grafana
- dời lọc và sampling ra edge
- gom metrics/logs/traces vào một control plane
- giữ kênh paging đã quen thuộc của on-call

Điểm quan trọng nhất:
- `Alerting/Routing` là capability khó thay nhất
- `Logs` là nơi tiết kiệm chi phí mạnh nhất
- `Traces` cần tail-based sampling để vừa tiết kiệm vừa giữ tín hiệu sự cố
- `Cardinality` phải bị chặn ở edge, không để vào backend rồi mới chữa
