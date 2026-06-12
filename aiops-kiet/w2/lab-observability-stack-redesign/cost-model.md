# Cost Model

## Giả định

Tôi dùng số liệu planning, không phải báo giá hợp đồng:
- Logs: `$0.50/GB` lưu trữ/ingest tương đương
- Metrics: tính theo active series, giả định khoảng `$0.05` mỗi 1,000 active series/tháng
- Traces: Tempo dùng object storage, giả định `$0.02/GB` cộng compute nhẹ
- Alerting: gần như giữ PagerDuty, chỉ thêm chi phí vận hành Grafana Alertmanager rất nhỏ

## Bảng chi phí

| Line item | Old Vendor | Old Cost | New Vendor | New Target Cost | Unit Driver | Current Scale |
|---|---|---:|---|---:|---|---:|
| Metrics ingest/query | Datadog Metrics | 14,000 | Grafana Mimir | 1,600 | 250k active series | 250k series |
| Logs ingest/search | Splunk Cloud | 16,000 | Grafana Loki | 2,700 | 35 TB/month log volume | 35 TB/month |
| Traces/APM | Datadog APM | 8,500 | Grafana Tempo | 1,100 | 40M spans/month | 40M spans |
| Alerting/routing | PagerDuty + routing extras | 2,000 | PagerDuty Business + Alertmanager | 2,000 | 65 engineers on-call | 65 engineers |
| UI / dashboards | Datadog UI + Splunk UI | 1,500 | Grafana Unified UI | 600 | 12 team dashboards | 12 dashboards |
| Collector / edge processing | N/A | 0 | OTel Collector | 1,000 | 10 nodes × DaemonSet | 10 nodes |
| S3 cold retention | N/A | 0 | S3 Archive | 600 | 60 TB retained 30+ days | 60 TB |
| Total |  | **42,000** |  | **9,600** |  |  |

## Nhận xét

Mức cắt giảm ước tính:

```text
1 - 9,600 / 42,000 = 77.1%
```

Mức này vượt yêu cầu 40% và nằm trong vùng 70-80% như đề mong muốn.

## Sensitivity

Nếu log volume tăng nhanh gấp 2 lần dự kiến, hạng mục đầu tiên vỡ budget là:
- `Loki ingest + storage`

Tác động:
- từ `2,700` lên khoảng `5,000 - 5,800`
- vẫn chưa vượt tổng budget 25,200 nếu metrics và traces giữ nguyên
- nhưng sẽ đẩy nhu cầu:
  - aggressive label drop
  - giảm retention nóng
  - chuyển nhiều log sang S3 cold archive

Kết luận:
- log là biến số chi phí nhạy nhất
- metrics và alert routing ổn định hơn
- trace cost tăng chậm hơn nếu tail sampling làm đúng

