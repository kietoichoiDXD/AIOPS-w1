# W1-D1: Metric Anomaly Detection

## Dataset

- Nguồn: Numenta Anomaly Benchmark (NAB)
- Series chính: `realKnownCause/machine_temperature_system_failure.csv`
- Ground truth: `data/raw/combined_windows.json`
- Tần suất: 5 phút / điểm

## EDA Summary

| Chỉ số | Giá trị |
|---|---:|
| Rows | 22695 |
| Start | 2013-12-02 21:15:00 |
| End | 2014-02-19 15:25:00 |
| Mean | 85.9265 |
| Std | 13.7469 |
| Skewness | -1.8337 |
| Min | 2.0847 |
| Max | 108.5105 |
| Labelled anomaly points | 2268 |

Nhận xét: dữ liệu lệch mạnh (skewed), có failure windows và regime shift, nên 3-sigma thuần không phải baseline tốt nhất.

## Screenshots

### 1) EDA plot

![EDA](/D:/AWS/AIOPS/artifacts/outputs/eda_template_vi.png)

### 2) Anomaly detection plot (2 detector)

![Detection comparison](/D:/AWS/AIOPS/artifacts/outputs/detection_comparison_vi.png)

### 3) Bảng so sánh Precision / Recall

| Detector | Precision | Recall | F1 | False Alarms |
|---|---:|---:|---:|---:|
| Rolling IQR | 0.1545 | 0.1093 | 0.1281 | 1357 |
| Isolation Forest (0.05) | 0.5970 | 0.2985 | 0.3980 | 457 |

## Detector 1: Rolling IQR

- Window: 288 điểm (24 giờ)
- Rule: anomaly nếu ngoài `[Q1 - 2.0 * IQR, Q3 + 2.0 * IQR]`
- Lý do chọn: robust hơn với data skewed/outlier

## Detector 2: Isolation Forest

Features dùng:

- value
- rolling_mean_1h
- rolling_std_1h
- rolling_mean_4h
- rate_of_change
- rate_of_change_25m
- lag_1
- lag_1h
- hour
- is_weekend
- z_score

## Log tuning contamination (3 lần)

| Contamination | Precision | Recall | F1 | TP | False Alarms | Missed |
|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.8370 | 0.0838 | 0.1523 | 190 | 37 | 2078 |
| 0.02 | 0.8722 | 0.1746 | 0.2910 | 396 | 58 | 1872 |
| 0.05 | 0.5970 | 0.2985 | 0.3980 | 677 | 457 | 1591 |

Best theo F1: `contamination=0.05`.

Ảnh chụp log tuning:

![Log tuning](/D:/AWS/AIOPS/artifacts/outputs/log_tuning_screenshot.png)

Ảnh chụp log so sánh detector:

![Log comparison](/D:/AWS/AIOPS/artifacts/outputs/log_comparison_screenshot.png)

## Model Artifact

- File: `artifacts/models/isolation_forest_machine_temperature.pkl`
- Kích thước: **624,666 bytes (~610.0 KB, < 1MB)**
- Trạng thái: đạt yêu cầu artifact nhỏ hơn 1MB

Ảnh chụp log model artifact:

![Log model artifact](/D:/AWS/AIOPS/artifacts/outputs/log_model_artifact_screenshot.png)

## Bonus

| Detector | Precision | Recall | F1 | False Alarms |
|---|---:|---:|---:|---:|
| EWMA | 0.1829 | 0.0481 | 0.0761 | 487 |
| Log + 3-sigma | 0.1095 | 0.0489 | 0.0676 | 903 |
| Multivariate IF | 0.7553 | 0.1406 | 0.2371 | 23 |

## Reflection

- Data thuộc loại: univariate metric time series, skewed mạnh, có failure windows và regime shift.
- Chọn method thống kê: Rolling IQR vì phù hợp dữ liệu skewed hơn 3-sigma.
- Chọn method ML: Isolation Forest với feature engineering theo ngữ cảnh thời gian.
- Detector tốt hơn: Isolation Forest tốt hơn Rolling IQR theo F1 (0.3980 > 0.1281), giảm false alarms đáng kể.
- Trade-off khi tune contamination: contamination tăng thì recall tăng nhưng false alarms cũng tăng.
- Production choice: ưu tiên Isolation Forest cho detector chính; giữ IQR làm baseline dễ giải thích cho vận hành.

## Files nộp

- `notebooks/assignment.ipynb`
- `SUBMIT.md`
- `data/raw/machine_temperature_system_failure.csv`
- `data/raw/combined_windows.json`
- `artifacts/outputs/eda_template_vi.png`
- `artifacts/outputs/detection_comparison_vi.png`
- `artifacts/outputs/comparison.csv`
- `artifacts/outputs/tuning_log.csv`
- `artifacts/models/isolation_forest_machine_temperature.pkl`
- `assets/knowledge_check/1-2.jpg`
- `assets/knowledge_check/3-4.jpg`
- `assets/knowledge_check/4-5.jpg`
