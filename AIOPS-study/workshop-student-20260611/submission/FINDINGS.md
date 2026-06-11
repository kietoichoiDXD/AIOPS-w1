# FINDINGS

## 1. Kết quả xác nhận chính

### Ex01 - Detect precursor

- `models/anomaly-detector.py` huấn luyện thành công từ baseline.
- Kết quả chạy với `S01 / esb / latency_p99_ms`:
  - Baseline mean: `901.0`
  - Baseline std: `19.1`
  - 3σ anomaly đầu tiên: `2026-06-09T08:16:00+00:00`
  - Alert thật: `2026-06-09T08:16:00+00:00`
  - IsolationForest anomaly đầu tiên: `2026-06-09T07:47:00+00:00`
  - Số anomaly theo 3σ: `23/105`
  - Số anomaly theo IsolationForest: `24/105`

### Ex02 - Correlate RCA

- `models/rca-engine.py` chạy đúng cho `S06`.
- Root cause kỳ vọng: `t24-service`
- Root cause top-1 của fusion: `t24-service`
- Kết quả này khớp với đề bài.

### Ex03 - Closed loop

- API server đã được khởi động để hỗ trợ dashboard và replay.
- Logic quyết định trong notebook vẫn giữ đúng ngưỡng:
  - confidence `< 0.4` thì page human
  - service không có remediation an toàn thì page human
- Khi trigger `S08`, stream sinh ra `2` alert chính:
  - `datapower network-connectivity`
  - `datapower error-rate-spike`

## 2. Bằng chứng dữ liệu

### Anomaly detector

- Đã train thành công: `57 IF models, 58 stats`
- Số mẫu trong chuỗi kiểm tra: `105`
- Số anomaly theo IF: `24/105`

### RCA

- PageRank top-1: `esb`
- Earliest drift top-1: `t24-service`
- Correlation top-1: `t24-service`
- Weighted RRF top-1: `t24-service`
- 4-way fusion top-1: `t24-service`
- Confidence khi quyết định remediation cho `S08`: `34.98%`
- Kết luận quyết định: `PAGE`

### Log clustering

- Tổng số cluster: `26`
- Top cluster:
  - TLS cert expired: `500`
  - DNS NXDOMAIN: `240`
  - Cached confirmation fallback: `180`

## 3. Nhận định kỹ thuật

1. `IsolationForest` phát hiện sớm hơn 3σ ở `S01` khoảng `29` phút, nên phù hợp làm cảnh báo tiền đề.
2. 3σ bám sát thời điểm alert thật trong `S01`, nên đây là detector ổn để so sánh với IF.
3. Với `S06`, PageRank đơn lẻ bị kéo về `esb` và `datapower`, trong khi earliest-drift đưa `t24-service` lên đầu rất rõ.
4. Granger trong notebook `ex02` cho kết quả top-1 là `bb-edge` và `esb`, nên đúng như ghi chú của workshop: đây là tín hiệu phụ, không nên tin tuyệt đối.
5. Weighted RRF giải quyết được tình huống một ranker yếu hơn các ranker còn lại và vẫn giữ `t24-service` ở top-1.
6. Log clusterer đã gom đúng các template lặp lại lớn, đủ để làm lớp chuẩn hóa log ban đầu.
7. Với `S10`, detector z-score phát hiện trước ngưỡng alert `10` phút, nên đây là khoảng lead time thực tế có thể dùng để cảnh báo sớm nhưng chưa nên auto-remediate.

## 4. Ảnh minh chứng

- `submission/screenshots/results-summary.png`

