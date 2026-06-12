# Risk Register

| Risk Description | Likelihood | Impact | Specific Mitigation | Owner |
|---|---|---|---|---|
| OTel Collector OOM khi tail-based sampling tăng đột biến | M | H | Giới hạn queue, memory request/limit rõ ràng, POC 5,000 req/s | Platform |
| Bỏ lỡ cửa sổ hủy Splunk 90 ngày | M | H | Đặt deadline procurement ngay từ Week 1 | Finance + Platform |
| Team chưa quen PromQL/LogQL | H | M | Cheat sheet, office hour, pairing on-call 2 tuần đầu | SRE Lead |
| Cardinality vẫn tăng do label từ app | H | H | Drop label ở edge, review schema telemetry | Platform |
| Route alert sai gây duplicate paging | M | H | Bật dedup/inhibition trước khi cutover | Incident Management |
| Mất trace quan trọng do policy sampling quá chặt | M | H | Tail sampling theo criticality và error policy, audit bằng canary traffic | Observability |

