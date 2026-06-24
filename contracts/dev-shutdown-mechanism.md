# Hướng dẫn Kỹ thuật: Cơ chế tự động tắt tài nguyên ở môi trường Dev (SCHEDULE_SHUTDOWN)

Tài liệu này hướng dẫn cách thức thực thi hành động can thiệp tự động **SCHEDULE_SHUTDOWN** (tắt tài nguyên lãng phí) trên môi trường **Dev / Sandbox / Staging** một cách an toàn và tự động.

---

## 1. Luồng xử lý E2E (End-to-End Workflow)

```
[AI Engine] ──(1. Phát hiện & Đề xuất)──► [CDO Platform]
                                              │
                                       (2. Assume Role)
                                              ▼
[Tài khoản Dev] ◄──(3. Stop Resource)─── [AWS SDK Boto3]
      │
 (Báo Slack) ──(4. Kỹ sư cần rollback?)──► [Bật lại ngay lập tức]
```

1. **AI Engine phát hiện**: AI Engine phân tích dữ liệu batch thấy tài nguyên `i-xxxx` hoặc `db-xxxx` ở tài khoản Dev hoạt động không tải liên tục. AI Engine trả về `"suggested_action": "SCHEDULE_SHUTDOWN"`.
2. **CDO Platform tiếp nhận**: CDO Platform đọc đề xuất, xác định tài nguyên thuộc tài khoản Dev.
3. **Thực thi (Containment)**: CDO Platform gọi AWS SDK dừng tài nguyên chéo tài khoản (Cross-account).
4. **Thông báo & Rollback**: Gửi tin nhắn Slack cho Owner. Nếu kỹ sư click nút Rollback, CDO sẽ khởi động lại tài nguyên ngay lập tức và báo cáo lỗi lên AI.

---

## 2. Mã nguồn thực thi bằng Python (AWS SDK Boto3)

CDO Platform sử dụng thư viện `boto3` để thực hiện tắt các loại tài nguyên phổ biến ở môi trường Dev:

### 2.1. Tắt EC2 Instance
```python
import boto3

def shutdown_ec2_instance(credentials, region, instance_id):
    # Khởi tạo client sử dụng temporary credentials chéo tài khoản
    ec2 = boto3.client(
        'ec2',
        region_name=region,
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )
    print(f"[+] Đang tắt EC2 Instance: {instance_id}")
    response = ec2.stop_instances(InstanceIds=[instance_id])
    return response['StoppingInstances'][0]['CurrentState']['Name']
```

### 2.2. Tắt RDS Database Instance
```python
import boto3

def shutdown_rds_instance(credentials, region, db_identifier):
    rds = boto3.client(
        'rds',
        region_name=region,
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )
    print(f"[+] Đang tắt RDS DB Instance: {db_identifier}")
    response = rds.stop_db_instance(DBInstanceIdentifier=db_identifier)
    return response['DBInstance']['DBInstanceStatus']
```

### 2.3. Tắt SageMaker Notebook Instance (Nguyên nhân gây spike chính của dự án)
```python
import boto3

def shutdown_sagemaker_notebook(credentials, region, notebook_name):
    sagemaker = boto3.client(
        'sagemaker',
        region_name=region,
        aws_access_key_id=credentials['AccessKeyId'],
        aws_secret_access_key=credentials['SecretAccessKey'],
        aws_session_token=credentials['SessionToken']
    )
    print(f"[+] Đang tắt SageMaker Notebook: {notebook_name}")
    response = sagemaker.stop_notebook_instance(NotebookInstanceName=notebook_name)
    return "Stopping"
```

---

## 3. Cấu hình phân quyền chéo tài khoản (Cross-Account IAM Roles)

Vì CDO Platform chạy ở tài khoản Quản trị (`Tools Account - 100000000001`), tài nguyên lãng phí nằm ở tài khoản Dev (`Dev Account - 200000000012`). Do đó bắt buộc phải sử dụng **AssumeRole**.

### Bước 1: Tạo IAM Role tại tài khoản Dev (`Dev Account`)
Tạo một IAM Role tên là `FinOpsContainmentRole` với chính sách Trust Policy và Permissions Policy:

*   **Trust Policy** (Cho phép Tools Account được assume role):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::100000000001:root"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

*   **Permissions Policy** (Chỉ cho phép STOP tài nguyên, tuyệt đối cấm DELETE hoặc TERMINATE):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:StopInstances",
        "rds:StopDBInstance",
        "sagemaker:StopNotebookInstance",
        "ec2:DescribeInstances",
        "rds:DescribeDBInstances",
        "sagemaker:DescribeNotebookInstances"
      ],
      "Resource": "*"
    }
  ]
}
```

### Bước 2: CDO Platform thực hiện Assume Role để lấy Credentials
Trong code Python chạy trên Tools Account, thực hiện gọi STS để lấy temporary credentials trước khi call API dừng tài nguyên:

```python
import boto3

def get_cross_account_credentials(target_account_id):
    sts_client = boto3.client('sts')
    assumed_role_object = sts_client.assume_role(
        RoleArn=f"arn:aws:iam::{target_account_id}:role/FinOpsContainmentRole",
        RoleSessionName="FinOpsContainmentSession",
        DurationSeconds=900
    )
    return assumed_role_object['Credentials']
```

---

## 4. Kế hoạch Khôi phục nhanh (Rollback Mechanism)

Khi dừng tài nguyên của dev, phải gửi ngay một tin nhắn cảnh báo qua Slack/Email cho Owner của tài nguyên đó kèm theo nút bấm **"Khôi phục khẩn cấp (Rollback)"**:

```
[FinOps Watch ALERT] 
Phát hiện SageMaker Notebook: 'notebook-instance-training-v2' chạy idle liên tục 48 giờ.
Hệ thống đã tự động dừng (Stop) tài nguyên để tránh lãng phí.
👉 Nếu đây là nhầm lẫn và bạn cần chạy tiếp, hãy click vào nút bên dưới:
[ BẬT LẠI NGAY LẬP TỨC (ROLLBACK) ]
```

*   **Khi click nút**: CDO Platform gọi lệnh `ec2.start_instances()` hoặc tương ứng để khởi động lại tài nguyên.
*   **Báo cáo sai lệch**: CDO gọi API của AI Engine: `POST /v1/audit/{audit_id}/rollback` để đánh dấu case này là False Positive, bảo vệ chỉ số SLO Error Budget cho dev team.
