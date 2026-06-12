# SUBMIT

## 1. Mục tiêu bài làm

Xây dựng một `evidence-driven remediation engine` nhận đầu vào là incident JSON gồm log, trace, metric và topology; đầu ra là:

- hành động khuyến nghị
- tham số hành động
- độ tin cậy `confidence`
- chuỗi bằng chứng `evidence`

Engine được triển khai đúng theo contract của handout:

```bash
python engine.py decide --incident eval/E01.json --history incidents_history.json --actions actions.yaml
```

## 2. Cấu trúc lời giải

- `engine.py`
  - entry point CLI
  - đọc incident, history, actions
  - gọi 3 lớp chính: `extract_features -> retrieve_and_vote -> select_action`
  - in JSON ra stdout và append vào `audit.jsonl`

- `features.py`
  - chuẩn hóa log token
  - gom keyword từ log
  - trích các cạnh trace `(from, to)`
  - tính `metric_anomaly_strength`
  - tạo `service_activity`

- `retrieval.py`
  - parse incident lịch sử
  - tính hybrid similarity
  - top-k retrieval
  - outcome-weighted voting

- `decision.py`
  - áp dụng heuristic escalation cho TLS / DNS / memory pattern
  - kiểm tra conflict giữa log và metric
  - tính utility theo cost / downtime / blast radius
  - chọn auto-action hoặc `page_oncall`

- `audit.jsonl`
  - 1 dòng JSON cho mỗi eval incident `E01..E08`

- `FINDINGS.md`
  - giải thích chi tiết thuật toán, công thức và cách quyết định

## 3. Thuật toán đã dùng

### Layer 1 - Trích xuất đặc trưng

Được cài trong `features.py`.

Các bước chính:

1. Tokenize log message bằng regex
2. Mask các token dạng số, IP, timestamp
3. Đếm keyword vận hành như `timeout`, `pool`, `deadlock`, `dns`, `tls`, `oom`, `memory`, `gc_pause`
4. Từ traces, gom các cặp `(from, to)` để biểu diễn hướng cascade
5. Từ metrics, lấy nửa đầu chuỗi làm baseline và tính anomaly strength kiểu z-score:

```text
anomaly_strength = |last - mu_baseline| / max(sigma_baseline, 1e-6)
```

### Layer 2 - Retrieval

Được cài trong `retrieval.py`.

Engine dùng `kNN-style retrieval` trên lịch sử incident.

Hybrid similarity:

```text
sim(q, h_i) = 0.40 * log_sim + 0.28 * trace_sim + 0.20 * metric_sim + 0.12 * service_sim + trigger_bonus
```

Trong đó:

- `log_sim` = weighted Jaccard trên `log_tokens`
- `trace_sim` = Jaccard trên `trace_pairs`
- `metric_sim` = Jaccard trên metric keys
- `service_sim` = Jaccard trên tập service
- `trigger_bonus = 0.12` nếu trigger service xuất hiện trong `affected_services`

Sau đó engine:

1. sắp xếp toàn bộ history theo similarity
2. lấy `top_k = 5`
3. bỏ phiếu cho action theo similarity, rank và outcome

Voting rule:

```text
vote(a) = Σ [ sim(q, h_i) * w_rank(i) * w_outcome(h_i) * w_action(a, h_i) ]
```

Với:

- `w_rank(i) = 1 / rank_i`
- `w_outcome = 1.0` nếu `success`
- `w_outcome = 0.6` nếu `partial`
- `w_outcome = 0.2` nếu `failed`
- `w_action = 0.35` nếu action là `page_oncall`, ngược lại `1.0`

### Layer 3 - Decision

Được cài trong `decision.py`.

Engine không lấy top-vote rồi auto-act ngay mà còn tính utility:

```text
p_success = vote(top_action) / Σ vote(a)
utility = 3.0 * p_success - 0.05 * cost - 0.08 * downtime - 0.12 * blast_radius
```

Các rule an toàn chính:

- TLS / certificate -> `page_oncall`
- DNS / NXDOMAIN -> `page_oncall`
- OOM / heap / GC pause -> ưu tiên `restart_pod`
- log service và metric service mâu thuẫn mạnh -> `page_oncall`
- similarity quá thấp -> `page_oncall`
- blast radius lớn nhưng confidence thấp -> `page_oncall`

## 4. Cách ghi thuật toán ra trong bài nộp

Để bài nộp rõ ràng và dễ chấm, tôi trình bày mỗi thuật toán theo cùng một mẫu:

1. Tên thuật toán
2. Input
3. Output
4. Các bước xử lý
5. Công thức toán
6. Lý do chọn

Ví dụ áp dụng trực tiếp vào bài này:

### Thuật toán 1 - Trích xuất đặc trưng incident

Input:

- incident JSON gồm `logs`, `traces`, `metrics`, `topology`

Output:

- `log_tokens`
- `log_keywords`
- `trace_pairs`
- `metric_anomaly_strength`
- `service_activity`

Các bước:

1. Tách token log bằng regex
2. Chuẩn hóa token bằng masking cho số, IP, timestamp
3. Đếm keyword vận hành quan trọng
4. Trích các cạnh trace `(from, to)`
5. Tính độ lệch metric cuối so với baseline đầu cửa sổ

Công thức:

```text
anomaly_strength = |last - mu_baseline| / max(sigma_baseline, 1e-6)
```

Lý do chọn:

- đơn giản
- minh bạch
- đủ mạnh cho dữ liệu incident ngắn

### Thuật toán 2 - Hybrid retrieval từ incident lịch sử

Input:

- feature của incident hiện tại
- feature của tập incident lịch sử

Output:

- danh sách `top_k` incident giống nhất
- vote cho từng action

Các bước:

1. Tính độ giống log
2. Tính độ giống trace
3. Tính độ giống metric
4. Tính độ giống service
5. Cộng trọng số thành hybrid similarity
6. Sắp xếp giảm dần và lấy `top_k = 5`

Công thức:

```text
sim(q, h_i) = 0.40 * log_sim + 0.28 * trace_sim + 0.20 * metric_sim + 0.12 * service_sim + trigger_bonus
```

Lý do chọn:

- tận dụng đủ log, trace, metric
- phù hợp tập dữ liệu nhỏ
- dễ audit hơn embedding đen hộp

### Thuật toán 3 - Outcome-weighted voting cho action

Input:

- `top_k` incident gần nhất
- action đã từng dùng trong history
- outcome của từng action trong history

Output:

- điểm vote cho từng action ứng viên

Các bước:

1. Với mỗi neighbor, lấy action tương ứng
2. Nhân similarity với rank weight
3. Nhân thêm outcome weight
4. Giảm trọng số nếu action là `page_oncall`
5. Cộng dồn vote theo action

Công thức:

```text
vote(a) = Σ [ sim(q, h_i) * w_rank(i) * w_outcome(h_i) * w_action(a, h_i) ]
```

Lý do chọn:

- không copy mù top-1
- ưu tiên precedent đã thành công
- tránh lạm dụng paging

### Thuật toán 4 - Utility-gated decision

Input:

- vote của các action
- metadata action trong `actions.yaml`

Output:

- action cuối cùng
- params
- confidence
- evidence

Các bước:

1. Chọn action có vote cao nhất
2. Chuẩn hóa vote thành `p_success`
3. Tính utility theo cost, downtime, blast radius
4. Chạy các guard rule TLS, DNS, OOM, conflict, OOD
5. Nếu rủi ro cao thì `page_oncall`, nếu không thì auto-act

Công thức:

```text
p_success = vote(top_action) / Σ vote(a)
utility = 3.0 * p_success - 0.05 * cost - 0.08 * downtime - 0.12 * blast_radius
```

Lý do chọn:

- decision dựa trên cả match quality lẫn risk
- đúng tinh thần remediation an toàn trong vận hành

## 5. Kết quả chạy

Đã chạy grader:

```text
Correct: 8/8
Forbidden: 0/8
Missing: 0/8
```

Chi tiết:

- `E01` -> `rollback_service`
- `E02` -> `page_oncall`
- `E03` -> `restart_pod`
- `E04` -> `page_oncall`
- `E05` -> `rollback_service`
- `E06` -> `page_oncall`
- `E07` -> `page_oncall`
- `E08` -> `page_oncall`

## 6. Điểm mạnh của lời giải

- Có dùng cả log + trace + metric, không vi phạm yêu cầu bài
- Có outcome-weighted voting, không ngây thơ theo top-1 neighbor
- Có OOD / escalation handling
- Có evidence chain trong `audit.jsonl`
- Có utility gate để tránh auto-action mù quáng

## 7. Giới hạn hiện tại

- Log parsing hiện tại là token-based heuristic, chưa phải Drain đầy đủ
- Similarity đang dùng trọng số tay, chưa có calibration học từ dữ liệu
- Confidence chưa phải xác suất được calibrate chuẩn
- Một số hard-coded rule như TLS / DNS / OOM làm engine an toàn hơn nhưng cũng ít tổng quát hơn

## 8. Cách chạy lại

```bash
python engine.py decide --incident eval/E01.json --history incidents_history.json --actions actions.yaml
python grade.py --audit audit.jsonl --expected eval/expected.json
```

## 9. Kết luận

Lời giải hiện tại đạt đủ yêu cầu functional của bài:

- chạy được
- audit được
- giải thích được
- đạt `8/8` trên bộ eval

Điểm quan trọng nhất là engine không chỉ “đoán action”, mà có pipeline rõ ràng từ evidence -> retrieval -> weighted voting -> safe decision.
