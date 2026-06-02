# W1-D2: Khai phá log, parse log và phát hiện bất thường

## Submission Layout

- `notebooks/assignment.ipynb`
- `d2_pipeline.py`
- `log_analyzer.py`
- `results/top_templates.csv`
- `artifacts/outputs/`

## Những gì đã hoàn thành

### Phase 1: Parse Log with Drain3

- Dataset sử dụng: HDFS từ Loghub
- File dữ liệu:
  - `data/raw/HDFS_100k.log_structured.csv`
  - `data/raw/anomaly_label.csv`
- Notebook load log có cấu trúc và đếm tổng số dòng
- Pipeline ưu tiên Drain3 khi có sẵn, nếu môi trường thiếu `drain3` thì có fallback để vẫn chạy được
- Liệt kê toàn bộ template và đếm số dòng mỗi template
- Xuất top-10 template ra `results/top_templates.csv`
- Ghi lại tuning `drain_sim_th` với các giá trị `0.3`, `0.5`, `0.7`

### Phase 2: Anomaly Detection on Log

- Tạo feature theo session/block của HDFS
- Áp dụng detector kiểu Isolation Forest
- Phát hiện session/template bất thường
- Tính precision / recall từ `anomaly_label.csv`

### Phase 3: Embedding + Cross-signal

- Tính TF-IDF similarity trên template
- Có thể gom các template giống nhau thành cụm
- Inject một dòng log lạ để kiểm tra phát hiện new template

### Phase 4: Mini Log Analyzer

- `log_analyzer.py` accepts one log file path
- It prints:
  - total line count
  - number of unique templates
  - top-5 templates with count and ratio
  - templates that spike in the latest 1-hour window
  - new templates in the latest 1-hour window

## Output

- Ảnh highlight bất thường: `artifacts/outputs/hdfs_anomaly_highlight.png`
- Ảnh top template: `artifacts/outputs/hdfs_top_templates.png`
- Ảnh template count time series: `artifacts/outputs/hdfs_template_count_timeseries.png`
- Template exports:
  - `results/top_templates.csv`
- Log tuning: `artifacts/outputs/tuning_log.csv`
- Metrics: `artifacts/outputs/hdfs_metrics.csv`

## Kết quả kiểm tra

Pipeline đã được kiểm tra trên:

- `HDFS_100k.log_structured.csv`
- `HDFS_2k.log` for the mini analyzer path

Tóm tắt HDFS từ structured log:

- Total lines: `104815`
- Unique templates: `19`
- Anomaly rate: `3.12%`
- Precision: `0.9667`
- Recall: `0.4633`
- F1: `0.6263`
- Top templates:
  - `Receiving block <*> src: /<*> dest: /<*>` - `23671`
  - `BLOCK* NameSystem.addStoredBlock: blockMap updated: <*> is added to <*> size <*>` - `23478`
  - `PacketResponder <*> for block <*> terminating` - `23451`
  - `Received block <*> of size <*> from /<*>` - `23447`
  - `BLOCK* NameSystem.allocateBlock:<*>` - `7940`
- Tuning `drain_sim_th`:
  - `0.3` -> `13` templates
  - `0.5` -> `13` templates
  - `0.7` -> `664` templates

## Reflection

- Drain3 rất hợp với log unstructured có mẫu lặp lại vì nó gom các dòng biến động vào template dùng lại được.
- Phát hiện template mới quan trọng vì nó thường báo hiệu deploy mới, lỗi mới, hoặc hành vi lạ chưa từng thấy.
- Spike của template hữu ích khi một mẫu lỗi cụ thể đột nhiên xuất hiện dày đặc trong một cửa sổ thời gian.
- Metric trả lời câu hỏi "cái gì đang sai", còn log trả lời "tại sao sai". Kết hợp cả hai sẽ rút ngắn thời gian tìm root cause.
- Structured JSON log thường dễ query hơn, còn plain text log thì hưởng lợi rất nhiều từ parsing.
- Với HDFS lần chạy này, parser nhóm được các dòng lặp lại khá tốt, nhưng recall của detector vẫn ở mức trung bình vì detector đơn giản chưa bắt hết mọi failure mode.

## Nhận Xét Bonus

Với log kiểu Docker-style của cùng một service, log JSON có lợi thế rất rõ vì các field như `timestamp`, `level`, `message`, `service`, `user`, `order` đã có cấu trúc sẵn nên dễ đếm, dễ lọc và ít template hơn. Ngược lại, plain text cần Drain3 hoặc regex parser để gom các dòng biến động vào cùng một template. Trong thử nghiệm của em, regex parser cho ra output ổn và dễ kiểm soát theo format đã biết, còn Drain3 linh hoạt hơn khi format log thay đổi hoặc khi xuất hiện pattern mới ngoài dự đoán. Vì vậy, nếu hệ thống đã log được JSON thì nên ưu tiên structured log; còn nếu là log cũ hoặc lẫn nhiều format thì Drain3 vẫn là lựa chọn an toàn hơn.
