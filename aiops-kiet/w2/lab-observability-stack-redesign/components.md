# Component Decision Table

| Capability | Chosen Component | Why this one (1 sentence) | What gets worse if changed in 6 months (1 sentence) |
|---|---|---|---|
| Metrics | Grafana Mimir | Mimir scale tốt cho time series lớn và tích hợp trực tiếp với Grafana, giảm phụ thuộc Datadog metrics. | Đổi sang backend khác sẽ làm tăng query friction và dễ làm gãy dashboard/alert rule đã migrate. |
| Logs | Grafana Loki | Loki giữ index nhỏ, query theo label + chunk nén tốt nên giảm chi phí lớn nhất so với Splunk. | Đổi lại Splunk hoặc ELK sau 6 tháng sẽ tăng chi phí lưu trữ và search latency quay lại. |
| Distributed tracing | Grafana Tempo | Tempo chỉ cần object storage, phù hợp mục tiêu giảm bill nhưng vẫn giữ trace đầy đủ hơn head sampling 1%. | Nếu đổi sang backend nặng hơn, trace cost và vận hành sẽ tăng mạnh, làm mất lợi thế kiến trúc mới. |
| Alerting/Correlation | Grafana Alertmanager | Alertmanager tập trung dedup, routing, inhibition và silencing trong một lớp rõ ràng. | Thay bằng routing rời rạc sẽ làm duplicate paging và giảm khả năng kiểm soát incident noise. |
| Incident routing | PagerDuty Business | Giữ PagerDuty giúp bảo toàn on-call schedule của 65 engineer và tránh thay đổi quy trình phản ứng sự cố. | Nếu bỏ PagerDuty quá sớm, team sẽ mất tính quen thuộc và thời gian phản ứng sẽ xấu đi trước khi training xong. |
| Dashboards | Grafana Unified UI | Một UI duy nhất giảm context switching giữa Datadog, Splunk và nhiều tab điều tra. | Nếu tách lại dashboard theo vendor, MTTR sẽ tăng vì on-call phải nhảy qua nhiều hệ thống. |

