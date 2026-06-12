# SUBMIT

## 1. Phạm vi đã hoàn thành

Bài workshop đã được chạy và kiểm chứng đầy đủ trên 3 notebook:

- `ex01-detect-precursor.ipynb`
- `ex02-correlate-rca.ipynb`
- `ex03-closed-loop.ipynb`

Các module lõi đã dùng:

- `models/anomaly-detector.py`
- `models/rca-engine.py`
- `models/log-clusterer.py`

Các kết quả đã xác nhận:

- detector anomaly chạy được cho `S01`
- RCA fusion tìm đúng root cause cho `S06`
- log clusterer gom được template log có ý nghĩa vận hành
- closed-loop decision logic vẫn giữ guardrail an toàn khi confidence thấp

## 2. Cách tôi áp dụng kiến thức của lab để giải bài

Tôi không giải bài theo kiểu chỉ chạy notebook để lấy kết quả, mà gắn từng phần với đúng nhóm kiến thức của workshop.

### Metric anomaly detection

Áp dụng:

- `3σ`
- `z-score`
- `IsolationForest`
- precursor signal analysis

Cách dùng trong bài:

- `3σ` được dùng như detector nền dễ giải thích
- `z-score` được dùng để đo mức lệch so với trạng thái ổn định
- `IsolationForest` được dùng để bắt tín hiệu bất thường sớm hơn detector ngưỡng cứng
- so sánh thời điểm anomaly đầu tiên với thời điểm alert thật để đo lead time

### Log mining

Áp dụng:

- tokenization
- masking
- template / pattern analysis
- log signal extraction

Cách dùng trong bài:

- `log-clusterer.py` chuẩn hóa log line thành template gần kiểu Drain đơn giản
- token số, IP, UUID, hex được mask để giảm nhiễu
- các pattern count lớn như TLS, DNS, timeout được dùng làm evidence cho RCA

### Observability

Áp dụng:

- metrics
- logs
- traces
- topology
- correlation
- RCA

Cách dùng trong bài:

- metrics dùng để phát hiện drift và đo earliness
- logs dùng để xác thực failure mode cụ thể
- topology dùng để truy ngược cascade thay vì chỉ nhìn service đang alert
- nhiều ranker RCA được fusion để tránh lệch khi một tín hiệu đơn lẻ sai

### Decision / remediation

Áp dụng:

- retrieval
- weighted voting
- utility
- blast radius
- escalation guard

Cách dùng trong bài:

- trong `ex03`, quyết định không chỉ dựa trên detector mà còn dựa trên confidence và mức an toàn của remediation
- confidence thấp thì `PAGE`
- nếu không có hành động đủ an toàn cho service đang gặp sự cố thì không auto-act

### Production thinking

Áp dụng:

- audit trail
- explainability
- safe auto-action

Cách dùng trong bài:

- mỗi phần đều có evidence cụ thể theo timestamp
- kết quả không dừng ở “service nào lỗi” mà còn giải thích “vì sao kết luận như vậy”
- remediation không được tự động chạy khi tín hiệu chưa đủ mạnh

## 3. Thuật toán và xử lý chính

### Thuật toán 1 - Phát hiện anomaly trên metric

Input:

- chuỗi metric theo thời gian của một `service/metric`

Output:

- timestamp bất thường đầu tiên
- số lượng điểm bất thường
- lead time so với alert thật

Các bước:

1. lấy baseline steady-state
2. tính `mean` và `std`
3. tính `z-score`
4. đánh dấu `3σ anomaly` nếu `|z| > 3`
5. chạy thêm `IsolationForest`
6. so sánh detector thống kê và detector ML

Công thức:

```text
z = (x - mean) / std
anomaly_3sigma nếu |z| > 3
```

### Thuật toán 2 - Gom cụm template log

Input:

- tập log line

Output:

- các cluster template
- top pattern theo tần suất

Các bước:

1. tokenize log line
2. mask token biến thiên
3. nhóm theo độ dài câu
4. so khớp theo tỉ lệ vị trí giống nhau
5. nếu đủ giống thì gộp vào cluster cũ
6. nếu không thì tạo cluster mới

Ý nghĩa:

- biến hàng trăm log line tương tự thành một template dễ đọc
- rút signal từ log mà không cần đọc từng dòng thô

### Thuật toán 3 - RCA đa ranker

Input:

- metrics incident
- alerts
- service topology

Output:

- danh sách service nghi ngờ root cause

Các ranker:

- reverse-topology PageRank
- earliest-drift
- correlation / drift-count

Fusion:

- weighted reciprocal rank fusion

Ý nghĩa:

- PageRank bắt cấu trúc topology
- earliest-drift bắt service lệch sớm nhất
- correlation bắt service có nhiều metric tham gia failure
- fusion giúp giảm rủi ro một ranker kéo sai toàn bộ RCA

### Thuật toán 4 - Quyết định có guardrail

Input:

- alerts
- RCA confidence
- remediation availability

Output:

- `AUTO-ACT` hoặc `PAGE`

Các bước:

1. lấy tín hiệu anomaly và RCA
2. ước lượng confidence
3. kiểm tra service có remediation an toàn hay không
4. nếu confidence thấp hoặc blast radius khó kiểm soát thì page human
5. chỉ auto-remediate khi tín hiệu đủ mạnh và hành động đủ an toàn

## 4. Kết quả thực tế

### Ex01 - Detect precursor

Với `S01 / esb / latency_p99_ms`:

- baseline mean: `901.0`
- baseline std: `19.1`
- anomaly đầu tiên theo `3σ`: `2026-06-09T08:16:00+00:00`
- anomaly đầu tiên theo `IsolationForest`: `2026-06-09T07:47:00+00:00`
- alert thật: `2026-06-09T08:16:00+00:00`
- số anomaly theo `3σ`: `23/105`
- số anomaly theo `IsolationForest`: `24/105`

Kết luận:

- `IsolationForest` phát hiện sớm hơn khoảng `29` phút
- `3σ` bám rất sát mốc alert thật, phù hợp làm detector explainable

### Ex02 - Correlate RCA

Với `S06`:

- expected root: `t24-service`
- fused top-1: `t24-service`
- earliest-drift top-1: `t24-service`
- correlation top-1 có `t24-service`
- reverse-topology ranker riêng lẻ vẫn bị kéo bởi downstream alerting services

Kết luận:

- một ranker đơn lẻ chưa đủ
- fusion là cách hợp lý hơn để khóa đúng root cause trong cascade nhiều hop

### Ex03 - Closed loop

Khi chạy stream:

- `S08` sinh `2` alert chính
- confidence RCA khoảng `34.98%`
- quyết định cuối là `PAGE`
- với `S10`, detector z-score phát hiện sớm hơn alert `10` phút

Kết luận:

- hệ thống đã có tín hiệu forecast / early warning
- nhưng decision layer vẫn giữ nguyên tắc an toàn, không auto-remediate khi support yếu

## 5. Giá trị kỹ thuật của lời giải

Điểm mạnh chính:

- dùng cả metric, log, topology thay vì chỉ nhìn một chiều
- kết hợp detector thống kê và detector học máy
- có log abstraction thay vì đọc log thô
- RCA có multi-ranker fusion thay vì one-shot ranking
- decision layer ưu tiên an toàn hơn là “tự động hóa cho bằng được”

## 6. Giới hạn hiện tại

- `IsolationForest` hiện mới dùng giá trị đơn biến, chưa thêm rolling feature hay lag feature
- log clustering mới ở mức heuristic fixed-depth, chưa phải Drain3 đầy đủ
- RCA correlation ranker hiện là drift-count proxy, chưa phải causal inference hoàn chỉnh
- decision logic trong `ex03` còn khá rule-based, chưa có utility model đầy đủ

## 7. Cách chạy lại

```bash
python models/anomaly-detector.py --scenario S01 --service esb --metric latency_p99_ms
python models/rca-engine.py --scenario S06
python models/log-clusterer.py --show 8
```

Notebook:

```bash
jupyter notebook exercises/
```

Riêng `ex03` cần chạy API server:

```bash
python stack/api.py
```

## 8. Ảnh minh chứng

- `submission/screenshots/results-summary.png`

## 9. Kết luận

Bài workshop hiện tại đã đạt đúng tinh thần của chuỗi lab:

- phát hiện anomaly sớm hơn alert thật
- dùng log pattern để tăng chất lượng triage
- dùng topology + fusion để làm RCA đáng tin hơn
- giữ guardrail ở decision layer để tránh auto-remediation mù quáng

Điểm quan trọng nhất là lời giải không chỉ “ra đáp án”, mà còn thể hiện được pipeline AIOps hoàn chỉnh:

```text
metric/log signals -> anomaly + pattern extraction -> RCA fusion -> guarded decision
```
