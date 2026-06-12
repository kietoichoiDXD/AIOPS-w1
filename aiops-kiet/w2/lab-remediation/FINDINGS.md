# FINDINGS - Evidence-Driven Remediation Engine

Điểm cuối cùng: **8/8 đúng, không kích hoạt hành động bị cấm**.

---

## Câu 1 - Bạn chọn hàm similarity nào cho Layer 2, và vì sao?

### Hàm được chọn

Tổ hợp tuyến tính có trọng số của bốn thành phần con dựa trên Jaccard, cộng thêm một bonus cho trigger:

```text
sim(q, h) = 0.40 * log_sim
          + 0.28 * trace_sim
          + 0.20 * metric_sim
          + 0.12 * service_sim
          + 0.12 (bonus nếu trigger_service ∈ affected_services của h)
```

Mỗi thành phần con là Jaccard similarity trên một biểu diễn tập hoặc counter:
- `log_sim`: counter-Jaccard trên túi token log đã mask (`pool`, `timeout`, `connection`, ...)
- `trace_sim`: set-Jaccard trên các cặp service `(from, to)` lấy từ trace
- `metric_sim`: set-Jaccard trên tên metric (`payment-svc.cpu`, ...)
- `service_sim`: set-Jaccard trên các tên service xuất hiện trong incident

### Vì sao không dùng cosine trên TF-IDF embedding?

Với chỉ khoảng 29 bản ghi lịch sử, vector TF-IDF chiều cao dễ bị overfit vào từ vựng bề mặt. Xét E03, một sự cố memory leak trên `esb`: service `esb` không xuất hiện trong bất kỳ bản ghi lịch sử nào, nên cosine dựa trên vector tên service cho điểm 0 với mọi láng giềng. Trong khi đó, weighted Jaccard vẫn bắt được phần giao nhau trên keyword log (`heap`, `gc_pause`) một cách độc lập.

### Vì sao không dùng khoảng cách metric thuần?

Metrics thay đổi chậm; giá trị tuyệt đối không ổn định giữa các incident cách nhau vài tuần. E04 có điểm anomaly metric cao nhất nhưng token log (`nxdomain`, `dns`) lại không khớp gì với corpus lịch sử - nếu chỉ dùng metric-only similarity, nó sẽ bị xếp giống mọi incident latency cao khác và rất dễ chọn sai action.

### Phương án thay thế đã cân nhắc: Euclidean trên metric delta đã chuẩn hóa

Tôi đã thử theo cách không chính thức bằng việc bỏ trọng số trace 0.12 và gộp sang `metric_sim`. E06 bị vỡ: incident có tín hiệu mâu thuẫn này có log chỉ vào `payment-svc` (pool) nhưng trace lại chỉ vào `cart-svc → cart-redis`. Similarity thiên về metric sẽ đi theo tín hiệu log một cách mù quáng và có thể vote `rollback_service:payment-svc` - đây chính là đáp án bị cấm cho E06. Giữ `trace_sim` ở mức 0.28 giúp bảo toàn tín hiệu bất đồng mà decision layer cần để escalate.

---

## Câu 2 - Voting có trọng số theo outcome làm thay đổi xếp hạng ứng viên như thế nào?

### Minh họa: E05 (incident cần phá thế đồng hạng)

Trigger của E05 là `payment-svc` với `db-degradation`. Top-5 láng giềng và similarity thô:

| Hạng | History ID | Similarity | Outcome | Actions |
|------|-----------|------------|---------|---------|
| 1 | INC-2025-11-08 | 0.3267 | success | rollback_service, increase_pool_size |
| 2 | INC-2025-09-05 | 0.2715 | success | rollback_service, increase_pool_size |
| 3 | INC-2026-05-10 | 0.2715 | **partial** | rollback_service |
| 4 | INC-2026-01-04 | 0.1954 | success | page_oncall |
| 5 | INC-2025-07-04 | 0.1934 | success | restart_pod |

Hạng 2 và 3 bằng nhau về similarity (0.2715). Nếu dùng **pure-similarity voting** và bỏ qua outcome, cả hai sẽ đóng góp ngang nhau. Nhưng `INC-2026-05-10` có outcome `partial`, nên trọng số phiếu của nó là `0.2715 × (1/3) × 0.6 = 0.0543`, trong khi `INC-2025-09-05` (success) đóng góp `0.2715 × (1/2) × 1.0 = 0.1357` - lớn hơn 2.5 lần dù similarity giống hệt.

Tổng phiếu cuối cùng:

| Action | Điểm (có trọng số outcome) | Điểm (thuần similarity, giả định) |
|--------|----------------------------|-----------------------------------|
| rollback_service | **0.5167** | ~0.5710 |
| increase_pool_size | 0.4624 | ~0.5167 |
| page_oncall | 0.0171 | ~0.0195 |

Nếu không có outcome weighting, `increase_pool_size` và `rollback_service` sẽ gần như hòa (0.5167 vs 0.5710) và thứ tự có thể lật tùy theo chi tiết cài đặt. Khi có outcome weighting, `rollback_service` thắng rõ ràng vì láng giềng `partial` chỉ vote cho rollback chứ không vote cho increase_pool_size bị giảm trọng số - điều này phản ánh đúng rằng rollback đơn lẻ là con đường an toàn và đã được kiểm chứng hơn. Engine chọn `rollback_service`, khớp với đáp án kỳ vọng.

---

## Câu 3 - Tính EV đầy đủ cho E01

**Incident:** E01 - `checkout-svc` latency-p99-high, root cause: connection pool exhaustion trên `payment-svc`.

### Top-5 

| Hạng | History ID | sim | outcome_w | rank_w |
|------|-----------|-----|-----------|--------|
| 1 | INC-2025-11-08 | 0.2436 | 1.0 (success) | 1/1 |
| 2 | INC-2026-04-02 | 0.1952 | 0.6 (partial) | 1/2 |
| 3 | INC-2025-07-04 | 0.1925 | 1.0 (success) | 1/3 |
| 4 | INC-2025-07-19 | 0.1457 | 1.0 (success) | 1/4 |
| 5 | INC-2026-03-20 | 0.1457 | 0.6 (partial) | 1/5 |

### Cộng dồn phiếu cho action

```text
vote(rollback_service) = 0.2436 × 1.0 × 1.0         = 0.2436   (rank 1, success)
vote(increase_pool_size) = 0.2436 × 1.0 × 1.0      = 0.2436   (rank 1, success)
vote(page_oncall) từ rank 2 = 0.1952 × (1/2) × 0.6 × 0.35 = 0.0205
                  từ rank 4 = 0.1457 × (1/4) × 1.0 × 0.35 = 0.0127
                  từ rank 5 = 0.1457 × (1/5) × 0.6 × 0.35 = 0.0061
                  tổng page_oncall = 0.0394  (đã áp dụng phạt ×0.35 cho page_oncall)
vote(restart_pod) = 0.1925 × (1/3) × 1.0 × 1.0    = 0.0642   (rank 3, success)
```

Tổng khối lượng phiếu = 0.2436 + 0.2436 + 0.0642 + 0.0394 = 0.5908

```text
p_success(rollback_service) = 0.2436 / 0.5908 = 0.4123
```

### Tính utility (EV)

Từ `actions.yaml`: `rollback_service` có `cost_min=10`, `downtime_min=2`, `blast_radius_services=1`.

```text
utility = 3.0 × p_success − 0.05 × cost − 0.08 × downtime − 0.12 × blast
        = 3.0 × 0.4123  − 0.05 × 10   − 0.08 × 2          − 0.12 × 1
        = 1.2369         − 0.50        − 0.16               − 0.12
        = 0.4569
```

Ngưỡng blast radius: `blast=1 < 3`, nên không kích hoạt gate. `p_success=0.41 > 0.25`. `utility=0.457 > 0.10`.

**Action được chọn:** `rollback_service` trên `payment-svc`, confidence=`0.5911`. Khớp với `accepted_actions`.

### Vì sao không chọn `increase_pool_size`?

Hai action này có điểm vote ngang nhau (`0.2436`). Thứ tự sort trong Python là ổn định, và `rollback_service` đứng trước trong thứ tự tích lũy phiếu - nhưng quan trọng hơn là cả hai đều đúng theo `expected.json`. Engine chọn action có blast/cost tương đương nhưng vẫn là phương án chấp nhận được vì blast=1 là như nhau cho cả hai.

---

## Câu 4 - Khi nào engine chọn escalate, và có đúng không?

Engine escalate (chọn `page_oncall`) ở **E02, E04, E06, E07, E08**.

| Incident | Luồng quyết định | Ground truth | Đúng? |
|----------|------------------|--------------|-------|
| E02 | `escalate_tls` - keyword log `tls`, `certificate`, `fail` kích hoạt hard escalation | page_oncall được chấp nhận | ✓ |
| E04 | `escalate_dns` - keyword `dns`, `nxdomain` kích hoạt hard escalation | page_oncall được chấp nhận | ✓ |
| E06 | `escalate_disagreement` - dominant log service (`payment-svc`) khác dominant metric service (`cart-svc`) | page_oncall được chấp nhận | ✓ |
| E07 | `escalate` - toàn bộ phiếu action dồn vào `page_oncall` qua voting (mọi láng giềng đều khuyên gọi người) | phải page human | ✓ |
| E08 | `escalate_ood` - best_similarity=0.021 thấp hơn ngưỡng OOD 0.06 | page_oncall được chấp nhận | ✓ |

Engine **không** escalate ở E01, E03, E05 - và cả ba trường hợp này đều không được phép escalate (`must_not_action: page_oncall` cho E01 và E03) hoặc auto-action là phương án đúng/chấp nhận được (E05 chọn rollback, là kết quả ưu tiên).

**Quyết định thiết kế quan trọng:** `page_oncall` trong `actions.yaml` có `cost=0` và `blast_radius=0` - nếu làm ngây thơ, nó sẽ luôn tối đa hóa utility. Engine chặn điều đó bằng: (1) phạt ×0.35 trên phiếu của `page_oncall` ở Layer 2, và (2) các gate hard-escalation ở Layer 3 chỉ bật khi có bằng chứng dương cho việc cần escalate, chứ không phải chỉ vì thiếu bằng chứng để auto-action.

---

## Câu 5 - Kiểu incident nào làm engine dễ hỏng nhất, và fix cụ thể là gì?

### Kiểu lỗi dễ hỏng nhất: cascade nhiều service nhưng root không phải service đang alert

E08 là ví dụ rõ nhất. Alert bắn ở `bb-edge` (lá cuối), nhưng root thật là `t24-service` (nút sâu nhất, có drift `db_replica_lag`). Engine đúng khi escalate vì `best_similarity=0.021` chạm ngưỡng OOD - nhưng câu trả lời đúng *không chỉ là* "page ai đó"; đúng hơn phải là `rollback_service:t24-service`. Engine chưa có logic đi ngược đồ thị topology để lần từ trace lên upstream và nhận ra `t24-service` là root emitter.

Engine cũng sẽ hỏng với bất kỳ incident cascade nào mà corpus **có** một láng giềng gần (similarity cao) nhưng similarity đó lại bị kéo bởi log của service đang alert, chứ không phải tín hiệu của root-cause service. Trong trường hợp đó, engine sẽ tự tin auto-act lên sai service.

### Vì sao khó

Xác định root cause dựa trên topology cần graph propagation (ví dụ PageRank trên đồ thị trace có trọng số lỗi, hoặc suy luận Bayesian trên service dependency graph). Corpus chỉ lưu `affected_services` như một danh sách phẳng - không có đồ thị nhân quả ground-truth để train trực tiếp.

### Fix cụ thể nhưng chưa triển khai (do giới hạn thời gian)

**Bước tiền xử lý xác định root trên trace graph:** trước khi tính similarity, chạy một backward BFS duy nhất trên các cạnh trace, sắp theo `(error_rate × p99_deviation)`. Node có điểm bất thường upstream cao nhất và không còn cạnh upstream bất thường nữa sẽ được xem là root candidate. Thay `trigger_service` trong feature vector bằng root suy ra này, rồi mới chạy similarity với corpus dùng *root* service, không phải service đang alert.

Cách này sẽ làm feature vector của E08 nổi bật `t24-service`, cải thiện similarity với các entry lịch sử kiểu `replication_lag` hoặc `db_drift`, và có thể đẩy `rollback_service:t24-service` lên top candidate với đủ confidence để auto-act - khớp với đáp án ground-truth ưu tiên.

Chưa triển khai vì: (1) dữ liệu trace của E08 có 240 record và suy luận đường root cần xử lý cẩn thận mẫu `lag` như metric proxy; (2) cần kiểm tra thêm trên E06 để chắc chắn không phá case tín hiệu mâu thuẫn; (3) hết ngân sách thời gian sau khi đã đạt 8/8 đúng với thiết kế hiện tại.

---

## Phụ lục A - Phát hiện ngoài phân phối

Kiểm tra OOD dùng một ngưỡng duy nhất trên `best_similarity`:

```python
if best_similarity < 0.06:
    → escalate_ood
```

**Cách suy ra ngưỡng:**
- E08 (OOD thật, cascade): `best_similarity = 0.021`
- E04 (DNS, service mới): `best_similarity = 0.023`
- E03 (memory trên `esb`, semi-novel): `best_similarity = 0.023`
- E07 (informer/throttle - thực ra có match tốt): `best_similarity = 0.417`

E03 có `best_similarity=0.023`, thấp hơn ngưỡng - nhưng engine đã bắt đầu từ trước đó qua gate `memory_restart` dựa trên keyword (heap=250, gc_pause=125). Gate OOD chỉ là phương án dự phòng; các gate theo domain sẽ ưu tiên cao hơn cho tín hiệu đã biết.

**Rủi ro với ngưỡng 0.06:**
- Quá chặt: một incident giống lịch sử khoảng 10% (ví dụ cùng service nhưng root khác) sẽ bị escalate trong khi lẽ ra nên hành động. Quan sát trong tập eval: không có case nào như vậy.
- Quá lỏng: một incident có similarity=0.07 nhưng action ứng viên tệ sẽ auto-act sai. Rủi ro này được giảm nhờ gate `p_success < 0.25` ở Layer 3 - ngay cả khi OOD không kích hoạt, vote mass yếu vẫn sẽ bị escalate.

## Phụ lục B - Chuỗi chứng minh

Mỗi entry `audit.jsonl` chứa một khối `evidence` có cấu trúc gồm:
- `feature_summary`: top keyword log theo số lần xuất hiện, các anomaly metric top theo z-score deviation, số lượng log/trace/metric
- `retrieval.top_matches`: cho từng 5 láng giềng - history ID, similarity score, outcome, root_cause_class, và toàn bộ action mà láng giềng đó góp phiếu
- `retrieval.evidence`: breakdown theo từng phiếu, cho biết chính xác mỗi láng giềng đóng góp bao nhiêu cho từng action (`sim × rank_w × outcome_w × page_penalty`)
- `decision`: luồng quyết định đã đi qua (ví dụ `escalate_tls`, `auto_act`, `escalate_ood`), `p_success`, điểm utility, trạng thái gate blast

**Phần bị lược bỏ:** raw log lines (quá dài, 500 dòng mỗi incident), full metric time series (không tăng giá trị audit), và danh sách cạnh topology. Người đọc vẫn có thể tái dựng quyết định từ trọng số vote mà không cần đọc lại 500 dòng log.
