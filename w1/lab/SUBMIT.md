# SUBMIT - Bài Lab ShopX

## Phạm Vi Nộp Bài

Bài nộp này bám đúng yêu cầu trong đề:

- mã phân tích có thể chạy lại
- ít nhất hai phương pháp phát hiện bất thường và có so sánh
- phân tích pattern log
- file `FINDINGS.md`
- file `SUBMIT.md`

Stack kỹ thuật cuối cùng được dùng trong bài:

- `EWMA` làm baseline làm mượt để bắt drift mịn
- `Rolling Z-score` làm baseline thống kê dễ giải thích
- `Isolation Forest` làm detector đa biến bổ trợ
- `CUSUM` là phương pháp chính cho phát hiện drift liên tục
- `Drain3` được dùng khi có sẵn, và có fallback regex để notebook vẫn chạy được

## Phát Biểu Nhiệm Vụ Của Nhóm

Nhóm phân tích `24 giờ telemetry` gồm `metrics + logs`, kết thúc tại thời điểm incident được suppressed. Báo cáo cần trả lời ba câu hỏi:

- `WHEN` - anomaly bắt đầu từ khi nào, và có silent signal hàng giờ trước alert hay không
- `WHERE` - service nào, metric nào, và log pattern nào là chỉ báo sớm nhất
- `WHAT` - giả thuyết root cause là gì, và cơ chế nào gây ra restart loop

## Ảnh Minh Họa

![Biểu đồ memory, GC và incident timeline](./artifacts/chart_03_memory_annotated.png)

![So sánh các phương pháp phát hiện bất thường](./artifacts/chart_04_anomaly_comparison.png)

![Dòng thời gian sự cố](./artifacts/chart_07_incident_timeline.png)

## Deliverables

- [`FINDINGS.md`](/D:/AWS/AIOPS/w1/lab/FINDINGS.md)
- [`SUBMIT.md`](/D:/AWS/AIOPS/w1/lab/SUBMIT.md)
- [`requirements.txt`](/D:/AWS/AIOPS/w1/lab/requirements.txt)
- [`scripts/run_pipeline.py`](/D:/AWS/AIOPS/w1/lab/scripts/run_pipeline.py)
- [`notebooks/01_metrics_anomaly_detection.ipynb`](/D:/AWS/AIOPS/w1/lab/notebooks/01_metrics_anomaly_detection.ipynb)
- [`notebooks/02_log_parsing_drain3.ipynb`](/D:/AWS/AIOPS/w1/lab/notebooks/02_log_parsing_drain3.ipynb)
- [`w1_aio_02_slide.html`](/D:/AWS/AIOPS/w1/lab/w1_aio_02_slide.html)
- [`artifacts/g3_recommended_lightweight_architecture.png`](/D:/AWS/AIOPS/w1/lab/artifacts/g3_recommended_lightweight_architecture.png)

## Tóm Tắt Phát Hiện Chính

- Tín hiệu JVM sớm nhất: `06:30:19Z`
- Tín hiệu root cache sớm nhất: `06:32:33Z`
- Memory tăng bền vững: `09:01:00Z`
- Memory vượt `60%` giới hạn: `18:22:00Z`
- `OOMKilled` đầu tiên: `19:59:02Z`
- Alert production: `23:04:00Z`
- Restart loop đạt `7` lần restart lúc `23:43:00Z`

Điều này cho thấy có một khoảng suy giảm âm thầm rất dài trước khi alert phản ứng.

## Phản Tư Nhóm

Phần khó nhất của bài là xác định đâu mới là thời điểm anomaly thực sự có ý nghĩa theo góc nhìn vận hành. Một số phương pháp có thể cho kết quả rất sớm, nhưng không phải timestamp nào cũng đủ thuyết phục để đưa vào postmortem. Thử thách lớn nhất không chỉ là chạy anomaly detection, mà còn là nối kết quả với hành vi service, log pattern và chuỗi lan truyền lỗi sao cho hợp lý với một SRE hoặc reviewer.

Điều hữu ích nhất là kết hợp metrics với logs thay vì xem chúng là hai phần rời nhau. Metrics cho thấy memory drift và tác động lên người dùng, trong khi logs chỉ ra cơ chế lỗi từ rất sớm. Đặc biệt, `GC overhead limit warning` và `ProductCatalogCache eviction failed` cho tín hiệu sớm mạnh hơn nhiều so với threshold alert đơn thuần. Nhờ vậy, nhóm điều chỉnh lại cách đọc timeline và cách đánh giá mức độ hữu ích của từng phương pháp phát hiện.

Nếu có thêm thời gian, nhóm sẽ tune `CUSUM` kỹ hơn để giảm false positive và thêm một pipeline online nhẹ để correlation giữa memory drift, GC pressure, và log template cache-eviction. Bài học lớn nhất là alert thường chỉ là đoạn cuối của câu chuyện, còn anomaly thật sự đã bắt đầu từ nhiều giờ trước. Nếu không kết hợp metrics và log-pattern analysis, khoảng lặng đó rất dễ bị bỏ sót.

## Đóng Góp Cá Nhân

| Thành viên | Vai trò | Đóng góp |
|---|---|---|
| Thành viên 1 | Lead analyst | Tổng hợp timeline sự cố và đối chiếu bằng chứng từ metrics và logs. |
| Thành viên 2 | Phân tích metrics | Xác thực memory, GC, latency, 5xx và restart pattern từ file CSV gốc. |
| Thành viên 3 | Phân tích log | Trích xuất template và xác nhận tín hiệu JVM/cache sớm từ log JSONL. |
| Thành viên 4 | Phát hiện bất thường | So sánh EWMA, Rolling Z-score, Isolation Forest và CUSUM cho dạng sự cố này. |
| Thành viên 5 | Trực quan hóa | Chuẩn hóa và làm sạch các biểu đồ cuối dùng trong report và notebook. |
| Thành viên 6 | Tài liệu | Viết và chỉnh sửa phần postmortem cuối cùng và narrative nộp bài. |
| Thành viên 7 | Review và thuyết trình | Kiểm tra tính nhất quán giữa các deliverable và chuẩn bị talking points. |

## Cấu Trúc Repo

```text
w1/lab/
|-- FINDINGS.md
|-- SUBMIT.md
|-- requirements.txt
|-- notebooks/
|   |-- 01_metrics_anomaly_detection.ipynb
|   `-- 02_log_parsing_drain3.ipynb
|-- scripts/
|   `-- run_pipeline.py
|-- artifacts/
|   |-- anomaly_method_comparison.csv
|   |-- ewma_results.csv
|   |-- rolling_zscore_results.csv
|   |-- chart_01_correlation_normalized.png
|   |-- chart_02_log_error_rate.png
|   |-- chart_03_memory_annotated.png
|   |-- chart_04_anomaly_comparison.png
|   |-- chart_05_multiservice_5xx.png
|   |-- chart_06_gc_scatter.png
|   |-- chart_07_incident_timeline.png
|   |-- chart_08_request_vs_latency.png
|   `-- log_templates_top12.png
`-- w1_aio_02_slide.html
```

## Lệnh Chạy

```bash
python scripts/run_pipeline.py
```

Hai notebook cũng có thể chạy tuần tự từ đầu đến cuối.

