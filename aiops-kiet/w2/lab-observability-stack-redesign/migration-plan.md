# 8-Week Migration Plan

## Week 1
- Action: bật OTel SDK song song với stack cũ trên 2 service ít rủi ro nhất.
- Rollback Path (under 30 mins): tắt env var export sang OTel, quay về agent cũ.
- Go/No-go Gate: không mất metric, không mất alert quan trọng.

## Week 2
- Action: triển khai OTel Collector DaemonSet ở edge cho logs/metrics/traces dual-shipping.
- Rollback Path (under 30 mins): disable export mới, collector vẫn giữ cấu hình cũ.
- Go/No-go Gate: không có bất kỳ blackout nào trong giờ làm việc.

## Week 3
- Action: bật tail-based sampling cho traces quan trọng và label dropping cho custom metrics.
- Rollback Path (under 30 mins): giảm sampling về probabilistic tạm thời.
- Go/No-go Gate: không tăng OOM/retry trên collector.

## Week 4
- Action: đẩy logs sang Loki cho một namespace, giữ Splunk song song.
- Rollback Path (under 30 mins): switch dashboard query về Splunk.
- Go/No-go Gate: query logs không chậm hơn baseline.

## Week 5
- Action: đẩy metrics sang Mimir cho dashboard và alert thử nghiệm.
- Rollback Path (under 30 mins): trả alert rule về Datadog.
- Go/No-go Gate: không lệch alert coverage.

## Week 6
- Action: đẩy traces sang Tempo, dùng Grafana làm nơi inspect end-to-end.
- Rollback Path (under 30 mins): switch trace link về Datadog APM.
- Go/No-go Gate: trace search và root-cause drill-down vẫn đủ nhanh.

## Week 7
- Action: bật Alertmanager dedup/inhibition và route một phần alert sang PagerDuty/Slack.
- Rollback Path (under 30 mins): trả routing về hệ cũ.
- Go/No-go Gate: số paging duplicate giảm, không mất alert quan trọng.

## Week 8
- Action: cắt chuyển dần phần lớn workload sang Grafana LGTM, chuẩn bị decommission vendor cũ.
- Rollback Path (under 30 mins): giữ dual-write thêm một tuần nếu cần.
- Go/No-go Gate: đạt target cost và MTTR, đội on-call chấp nhận workflow mới.

