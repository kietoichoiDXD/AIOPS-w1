# FINDINGS - GeekShop Observability Redesign

## 1. Tóm tắt

Thiết kế mới chuyển GeekShop từ stack observability phân mảnh sang một đường ống chuẩn hóa dựa trên OpenTelemetry và Grafana LGTM.

Mục tiêu đạt được:
- giảm chi phí quan sát từ `$42,000/tháng` xuống khoảng `$9,600/tháng`
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

## 5. Mức tối ưu chi phí mới

Sau khi research lại pricing và các đòn bẩy kỹ thuật, tôi có thể kéo chi phí xuống thấp hơn nữa:

- Mimir: khoảng `$1,600`
- Loki: khoảng `$2,700`
- Tempo: khoảng `$1,100`
- Grafana UI: khoảng `$600`
- OTel Collector: khoảng `$1,000`
- S3 cold retention: khoảng `$600`
- PagerDuty + Alertmanager: khoảng `$2,000`

Tổng mới ước tính:

```text
9,600 / 42,000 = 22.9% của chi phí cũ
```

Tức là giảm khoảng:

```text
77.1%
```

Đây là mức tối ưu hơn, với giả định chúng ta:
- drop label mạnh hơn ở edge
- tăng tỷ lệ log sang cold storage
- giữ tail sampling chặt hơn cho traces non-critical
- giữ metrics ở mức cardinatility thấp và ổn định

## 6. Cách xử lý khi scale lớn hoặc phải duy trì lâu dài

Nếu GeekShop đi từ cỡ `1,000 users` lên `1,000,000 users`, bài toán observability không còn là “chọn tool nào” mà là “kiểm soát tín hiệu nào được phép đi vào tool”.

### 6.1 Ở mức khoảng 1,000 users

- OTel Collector vẫn đủ nhẹ nếu policy sampling hợp lý.
- Cardinality chưa vỡ ngay nhưng đã cần label allowlist.
- Logs có thể giữ hot retention tương đối rộng hơn.
- Alert noise bắt đầu xuất hiện nếu routing chưa chuẩn hóa.

### 6.2 Ở mức khoảng 1,000,000 users

- Logs là điểm vỡ budget đầu tiên nếu retention và label không bị siết.
- Metrics sẽ vỡ nếu custom labels sinh series explosion.
- Traces phải chuyển sang policy-based tail sampling.
- Alerting phải có dedup, inhibition, và ownership theo service/team.

### 6.3 Nếu phải duy trì lâu dài

Tôi sẽ thêm các lớp kỹ thuật sau:

- `Default deny` cho label telemetry
- `Sampling by importance` thay vì lấy mẫu đồng đều
- `Hot/Warm/Cold storage tiers`
- `Quota per namespace/team`
- `Cost dashboard` như một SLO vận hành
- `Retention review` định kỳ để ngăn chi phí creep

### 6.4 Kinh nghiệm kỹ thuật rút ra

- Đừng để backend sửa cardinality muộn, phải chặn ở edge.
- Đừng cắt PagerDuty trước, vì alert routing là capability khó thay nhất.
- Đừng giữ trace 100% cho traffic lớn, tail sampling là điểm cân bằng tốt hơn.
- Đừng để logs nằm mãi trên hot path, cold archive là bắt buộc khi tăng trưởng thật.
