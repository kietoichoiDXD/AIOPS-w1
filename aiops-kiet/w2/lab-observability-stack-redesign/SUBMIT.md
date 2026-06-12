# SUBMIT

## Hoàn thành

Tôi đã thiết kế lại stack observability cho GeekShop theo hướng:
- OpenTelemetry Collector ở edge
- Grafana Mimir cho metrics
- Grafana Loki cho logs
- Grafana Tempo cho traces
- Grafana Alertmanager route sang PagerDuty và Slack
- Grafana Unified UI cho on-call

## Deliverables

- `architecture.mmd`
- `components.md`
- `cost-model.md`
- `adr-001-otel-collector.md`
- `adr-002-grafana-lgtm-cloud.md`
- `migration-plan.md`
- `risks.md`
- `FINDINGS.md`
- `FINDINGS-vi.md`

## Kết luận ngắn

Thiết kế này giữ nguyên khả năng phản ứng sự cố, giảm chi phí mạnh bằng cách gom observability về một pipeline chuẩn hóa, và giảm MTTR nhờ một UI và một lớp routing rõ ràng.

