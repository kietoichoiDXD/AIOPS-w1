# FINDINGS

Tài liệu này tổng hợp các kết quả, thuật toán và bằng chứng kỹ thuật của workshop bằng tiếng Việt.

## 1. Tóm tắt kết quả

Workshop này thể hiện khá rõ một pipeline AIOps thực tế gồm 4 tầng:

1. phát hiện bất thường trên metric
2. gom và rút signal từ log
3. correlation + RCA trên topology
4. decision logic có guardrail

Kết quả chạy thực tế cho thấy:

- `IsolationForest` phát hiện precursor sớm hơn `3σ` trong `S01`
- RCA fusion xác định đúng root cause `t24-service` trong `S06`
- log clusterer trích được các template có nghĩa vận hành rõ ràng
- decision layer trong `S08` chọn `PAGE` thay vì auto-act khi confidence thấp

## 2. Phân tích theo nhóm kiến thức

## 2.1 Metric anomaly detection

### Dùng `3σ` và `z-score` để làm baseline explainable

Trong `anomaly-detector.py`, mỗi cặp `(service, metric)` được lấy baseline từ cửa sổ steady-state đầu tiên. Sau đó tính:

```text
z = (x - mean) / std
```

và đánh dấu anomaly nếu:

```text
|z| > 3
```

Điểm mạnh:

- rất dễ giải thích
- phù hợp để so với alert threshold thật
- cho phép xác định chính xác “điểm nào vượt bình thường”

Điểm yếu:

- khó bắt drift phi tuyến hoặc drift nhỏ nhưng bền
- nhạy với giả định baseline ổn định

### Dùng `IsolationForest` để bắt precursor signal

Module hiện tại train một `IsolationForest` cho từng `(service, metric)` bằng dữ liệu baseline, sau đó dùng `decision_function`.

Theo tài liệu scikit-learn, điểm anomaly thấp hơn tương ứng mẫu bất thường hơn, và với `decision_function`, giá trị âm được xem là outlier. Đây khớp với logic đang dùng trong code: `if_score < 0` thì đánh dấu anomaly. Nguồn:

- [IsolationForest — scikit-learn](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html)
- [Outlier detection — scikit-learn](https://scikit-learn.org/stable/modules/outlier_detection.html)

Kết quả `S01`:

- `3σ` anomaly đầu tiên: `2026-06-09T08:16:00+00:00`
- `IsolationForest` anomaly đầu tiên: `2026-06-09T07:47:00+00:00`

Suy ra:

- `IsolationForest` cho lead time sớm hơn `29` phút
- `3σ` phù hợp làm detector chuẩn hóa, còn `IsolationForest` hữu ích cho precursor detection

### Ý nghĩa vận hành

Nếu dùng thực tế:

- `3σ` phù hợp cho dashboard, on-call explainability, postmortem
- `IsolationForest` phù hợp làm signal sớm để triage hoặc tăng mức quan sát
- không nên auto-remediate chỉ từ precursor signal đơn lẻ

## 2.2 Log mining

### Tokenization và masking

`log-clusterer.py` dùng:

- split token theo khoảng trắng và ký tự phân tách
- mask số, IP, UUID, HEX

Mục tiêu:

- giảm số lượng template giả do biến động payload
- gom các log giống nhau về mặt ngữ nghĩa thành cùng một cụm

Đây là cách làm đúng tinh thần log mining cơ bản: chuyển raw text thành dạng có cấu trúc hơn trước khi phân tích.

### Template / pattern analysis

Clusterer dùng cách gần kiểu Drain đơn giản:

1. nhóm theo độ dài token
2. tìm cluster đang có với tỉ lệ vị trí khớp cao nhất
3. nếu độ giống đủ lớn thì nhập cụm
4. nếu không thì tạo cụm mới

Kết quả:

- tổng `26` cluster
- top cluster:
  - TLS cert expired: `500`
  - DNS NXDOMAIN: `240`
  - cached confirmation fallback: `180`

Ý nghĩa:

- log không chỉ được “đọc”
- log đã được nén thành pattern có thể dùng làm evidence cho RCA và triage

### Log signal extraction

Từ top cluster, ta thấy ba loại failure mode nổi bật:

1. lỗi certificate hết hạn
2. lỗi DNS resolution
3. fallback do upstream unreachable

Đây đều là các mẫu có giá trị RCA cao hơn nhiều so với việc chỉ biết `ERROR count tăng`.

## 2.3 Observability: metric + log + topology

Theo tài liệu OpenTelemetry, observability có giá trị khi các tín hiệu telemetry được liên kết thay vì đứng riêng lẻ. Nguồn:

- [OpenTelemetry Docs](https://opentelemetry.io/docs/)
- [What is OpenTelemetry?](https://opentelemetry.io/docs/what-is-opentelemetry/)

Bài này áp dụng đúng tư duy đó:

- metric cho biết cái gì lệch
- log cho biết lỗi gì đang xảy ra
- topology cho biết lỗi lan theo hướng nào

### Vì sao topology quan trọng trong `S06`

Trong cascade nhiều hop, service đang alert chưa chắc là root cause. Nếu chỉ nhìn downstream alerting services thì rất dễ sửa nhầm chỗ.

`rca-engine.py` vì vậy dùng:

- reverse-topology PageRank
- earliest-drift ranker
- correlation ranker
- weighted RRF fusion

Kết quả thực tế `S06`:

- PageRank top-1 riêng lẻ: `esb`
- earliest-drift top-1: `t24-service`
- correlation top-1 có `t24-service`
- fused top-1: `t24-service`

Điều này cho thấy:

- topology-only ranking chưa đủ
- time-to-drift là tín hiệu RCA rất mạnh
- fusion giúp ổn định hơn so với tin tuyệt đối vào một ranker

## 2.4 Correlation và RCA

### Earliest drift

Thuật toán này tìm service có metric vượt `3σ` sớm nhất sau baseline. Về RCA, đây là một heuristic hợp lý vì nguyên nhân gốc thường xuất hiện trước chuỗi triệu chứng downstream.

### Correlation / drift-count proxy

Ranker thứ ba đếm số metric trên một service cùng drift sau baseline. Dù chưa phải causal inference thật sự, nó vẫn hữu ích như một chỉ báo “service này tham gia mạnh vào sự cố”.

### Weighted reciprocal rank fusion

`rca-engine.py` gộp ba ranking bằng weighted reciprocal rank fusion:

```text
score(s) = Σ w_r / (k + rank_r(s))
```

RRF là một kỹ thuật fuse ranking cổ điển, đơn giản nhưng thường ổn định hơn từng ranker riêng lẻ. Nguồn:

- [Cormack et al. 2009 PDF](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)

Trong workshop, điều này giải thích vì sao:

- một ranker bị kéo sai vẫn không làm gãy toàn bộ RCA
- `t24-service` vẫn giữ được top-1 ở kết quả fused

## 2.5 Decision / remediation

### Guardrail quan trọng hơn auto-action

`ex03` cho thấy một nguyên tắc rất đúng cho production:

- anomaly detection không đồng nghĩa với remediation
- RCA chưa đủ chắc thì phải page human

Kết quả `S08`:

- stream sinh `2` alert chính
- confidence RCA khoảng `34.98%`
- quyết định cuối là `PAGE`

Với `S10`:

- detector z-score phát hiện sớm hơn alert `10` phút

Ý nghĩa:

- hệ thống có khả năng early warning
- nhưng decision layer vẫn tách riêng “phát hiện” khỏi “hành động”

### Blast radius và safe auto-action

Dù notebook không triển khai utility function đầy đủ như lab remediation engine, nó đã có đúng tinh thần:

- confidence thấp thì không tự sửa
- service không có remediation đủ an toàn thì không tự sửa
- human vẫn là lớp chặn cuối cho case mơ hồ

Đây là điểm rất quan trọng vì trong production:

- false positive ở alert chỉ gây phiền
- false positive ở remediation có thể gây outage lớn hơn

## 2.6 Audit trail và explainability

Bài này có thể giải thích được gần như toàn bộ chain:

- detector nào phát hiện trước
- timestamp nào bắt đầu lệch
- log pattern nào nổi bật
- ranker nào kéo RCA lên
- tại sao decision cuối cùng là `PAGE`

Đây chính là giá trị của explainable AIOps:

- on-call hiểu được vì sao hệ thống kết luận như vậy
- postmortem có thể truy lại evidence
- team vận hành tin hệ thống hơn vì không bị “black box”

## 3. Đọc trực tiếp từ code: vì sao dùng các kỹ thuật này

## 3.1 `models/anomaly-detector.py`

Điểm đúng:

- train theo baseline steady-state
- vừa giữ detector thống kê vừa có detector ML
- lưu cả `baseline_mean`, `baseline_std`, `z_score`, `if_score`

Vì sao hợp lý:

- bài học anomaly detection thường nên bắt đầu từ baseline explainable
- sau đó mới thêm detector mạnh hơn để tăng lead time

Giới hạn:

- hiện mới dùng 1 biến đầu vào cho mỗi model
- chưa thêm rolling mean, lag, rate-of-change

## 3.2 `models/log-clusterer.py`

Điểm đúng:

- mask token biến thiên
- gom log theo template thay vì chỉ count level
- dùng similarity theo vị trí token

Vì sao hợp lý:

- dễ triển khai
- đủ tốt cho khối lượng workshop
- bám sát tư duy log abstraction

Giới hạn:

- chưa có parse tree như Drain3 đầy đủ
- chưa tracking new-template rate theo thời gian

## 3.3 `models/rca-engine.py`

Điểm đúng:

- không dựa vào chỉ một ranker
- có topology-aware reasoning
- có earliness signal
- có fusion

Vì sao hợp lý:

- RCA thật hiếm khi đáng tin nếu chỉ nhìn score một chiều
- fusion giúp tăng tính robust trong cascade

Giới hạn:

- correlation ranker hiện còn khá thô
- chưa dùng trace-level causal evidence

## 4. Kết quả chốt

### Ex01

- baseline mean: `901.0`
- baseline std: `19.1`
- first `3σ` anomaly: `2026-06-09T08:16:00+00:00`
- first `IsolationForest` anomaly: `2026-06-09T07:47:00+00:00`
- lead time sớm hơn: `29` phút

### Ex02

- expected root: `t24-service`
- fused top-1: `t24-service`

### Ex03

- `S08` decision: `PAGE`
- RCA confidence: `34.98%`
- `S10` z-score lead time: `10` phút

### Log clustering

- tổng cluster: `26`
- top cluster TLS: `500`
- top cluster DNS: `240`

## 5. Kết luận

Nếu ghép lại toàn bộ workshop theo đúng tư duy AIOps, ta có pipeline sau:

```text
metric drift detection
-> log pattern abstraction
-> topology-aware RCA
-> confidence-gated remediation decision
```

Điểm làm bài này tốt không nằm ở chỗ có nhiều model phức tạp, mà ở chỗ mỗi tầng đều có vai trò rõ:

- metric phát hiện sớm
- log giải thích failure mode
- topology sửa lỗi “alerting service != root cause”
- decision layer giữ an toàn cho vận hành

Nói ngắn gọn, đây là một lời giải đúng hướng production hơn là chỉ đúng về mặt notebook.
