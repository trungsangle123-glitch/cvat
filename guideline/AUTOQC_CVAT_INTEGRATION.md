# Tích hợp AutoQC Pipeline vào CVAT

Tài liệu này mô tả cách đưa pipeline kiểm chất lượng nhãn từ lab AutoQC vào
project CVAT này mà không trùng lặp tính năng Quality Control đã có sẵn.

## 1. Kết luận kiến trúc

Nên chọn kiến trúc lai:

```text
CVAT Task / Job
  -> CVAT SDK hoặc REST API
  -> AutoQC worker
  -> Machine issues
  -> CVAT Quality Control / review flow
  -> Người duyệt sửa nhãn
  -> AutoQC gate
  -> Dataset export sạch
```

Nên triển khai theo ba lớp:

1. **CVAT layer:** task, job, frame, annotation, assignee và quyền truy cập.
2. **AutoQC worker:** kiểm quy tắc, model checker, sửa an toàn, calibration và gate.
3. **Optional UI:** Chrome extension hoặc trang React để xem issue, mở frame và chạy QC.

Không nên viết toàn bộ pipeline trong JavaScript của browser extension.
Browser chỉ nên điều khiển worker và hiển thị kết quả.

## 2. Chức năng đã có trong CVAT

CVAT đã cung cấp phần lớn quy trình người duyệt và đánh giá chất lượng:

- Ground Truth và Honeypot.
- Quality settings và quality requirement.
- So sánh annotation với Ground Truth.
- Consensus replicas.
- Conflict và review report.
- Chỉ định annotator/reviewer cho job.
- Job stage và state.
- REST API quality:
  - `/api/quality/reports`
  - `/api/quality/conflicts`
  - `/api/quality/settings`
  - `/api/quality/settings/requirements`
- Xuất/import annotation và dataset.

Các phần này không nên tự lập trình lại trong AutoQC:

- Cơ chế tài khoản và phân quyền.
- Hàng đợi task/job.
- Ground Truth conflict.
- Consensus merge.
- Theo dõi người duyệt.
- Export format của CVAT.
- Job stage/state và event log.

Khi mở rộng backend, nên tái sử dụng module
`cvat/apps/quality_control` thay vì tạo một module review song song.

## 3. Phần cần lấy từ AutoQC

AutoQC bổ sung kiểm tra ở mức machine/dataset mà CVAT Quality Control
không thay thế mặc định:

| Năng lực | Phần của pipeline |
|---|---|
| Nhận dữ liệu | Intake, kiểm ảnh hỏng, kích thước, duplicate, rò rỉ |
| Kiểm format YOLO | Số cột, class ID, box zero, box out-of-image, duplicate box |
| Ý kiến thứ hai | Model checker, missing/wrong/loose/false-positive |
| Tự sửa an toàn | Drop line, clip box, rename class, remove image |
| Lập hàng đợi | Gom issue theo ảnh và tính priority |
| Calibration | Sweep threshold trên bộ calib có đáp án |
| Gate | Release, Hold hoặc Rework |
| Xuất sạch | Dataset + manifest truy vết |

Các module này nên giữ làm thư viện Python độc lập:

```text
autoqc/
  common.py
  checks/
  calibrate.py
  autofix.py
  gate.py
  export.py
  cvat_adapter.py
```

Không copy logic sang JavaScript. Adapter chỉ chuyển đổi dữ liệu CVAT sang
đối tượng mà AutoQC hiểu.

## 4. Luồng dữ liệu

### 4.1 Chạy QC cho một job

1. Worker nhận `job_id` hoặc `task_id`.
2. Worker xác thực bằng Personal Access Token hoặc account service.
3. Worker lấy danh sách frame và annotation qua CVAT SDK.
4. Worker chuyển annotation sang format trung gian:

```json
{
  "frame": 12,
  "shape_id": 345,
  "label": "car",
  "bbox": [x1, y1, x2, y2]
}
```

5. Worker chạy intake, format checks, duplicate checks và model checks.
6. Worker lưu `Issue`, `Fix`, `ReviewItem` và gate result.
7. Worker trả kết quả cho CVAT UI/extension.

### 4.2 Review của người

1. Người duyệt mở danh sách `ReviewItem`.
2. Worker hoặc extension điều hướng tới frame tương ứng.
3. Người duyệt sửa annotation trong CVAT.
4. Sau khi lưu, worker chạy lại QC.
5. Hạng mục đã review được loại khỏi danh sách cảnh báo.
6. Gate tính lại tỷ lệ cảnh báo chưa review.

### 4.3 Xuất dữ liệu sạch

Chỉ xuất khi kết luận không phải `Rework`.

- `Release`: export là dataset phát hành.
- `Hold`: export là bản nháp để thử nghiệm.
- `Rework`: không export theo luồng mặc định.

Manifest nên tham chiếu tới task/job, config SHA-1, timestamp, danh sách
issue, danh sách thay đổi và quyết định gate.

## 5. Adapter CVAT

Tách AutoQC khỏi CVAT bằng một adapter duy nhất.

```python
class CvatAutoQcAdapter:
    def get_job(self, job_id: int) -> CvatJobSnapshot: ...
    def get_annotations(self, job_id: int) -> list[AnnotationRecord]: ...
    def get_frame(self, job_id: int, frame: int) -> bytes: ...
    def apply_fix(self, job_id: int, fix: Fix): ...
    def create_report(self, job_id: int, result: AutoQcResult): ...
```

Ví dụ có thể dùng CVAT SDK để:

- Lấy task và danh sách job.
- Lấy labels và frame count.
- Export annotation/dataset.
- Tạo export file.
- Chạy report ở task hoặc job level.

REST API cũng có thể được dùng cho các thao tác cập nhật annotation:

```text
GET  /api/jobs/{id}/annotations
PATCH /api/jobs/{id}/annotations/?action=create
PATCH /api/jobs/{id}/annotations/?action=delete
PATCH /api/jobs/{id}/annotations/?action=update
```

Worker nên dùng access token hoặc token dịch vụ. Không lấy CSRF/cookie từ
extension để xác thực một service dài hạn.

## 6. Model thứ hai

Model có thể chạy theo hai cách:

### FastAPI service

Thích hợp cho tích hợp từng frame và ít tài nguyên.

```text
POST /autoqc/predict
{
  "job_id": 42,
  "frame": 12,
  "image": "<base64>"
}
```

Server có thể dùng YOLO26, SAM 3 hoặc model custom.

### Worker batch

Thích hợp cho toàn task:

```text
RQ job: autoqc_task(task_id, config)
  -> tải frame
  -> cache predictions
  -> lưu issue
  -> tạo gate report
```

Nên lưu dự đoán model theo job/frame để chạy lại QC không gọi model nhiều lần.

## 7. Lưu trữ dữ liệu tích hợp

Tạo app Django hoặc database schema riêng cho trạng thái AutoQC.

Mỗi bảng nên chứa ít nhất:

| Bảng | Nội dung |
|---|---|
| `AutoQcRun` | task/job, config hash, thời gian chạy, verdict |
| `AutoQcIssue` | code, severity, frame/shape/line, message, extra |
| `AutoQcFix` | issue, action, before, after |
| `AutoQcReviewItem` | issue, priority, assignee, reviewed status |
| `AutoQcReviewEvent` | người duyệt, action, timestamp |
| `AutoQcExport` | export format, manifest, decision |

Không lưu cache model hoặc file frame trong database. Chỉ lưu tham chiếu
frame/path hoặc object storage key.

## 8. Tái sử dụng Quality Control

AutoQC issue nên được ánh xạ sang review surface sẵn có của CVAT:

| AutoQC | CVAT |
|---|---|
| Ảnh có lỗi bắt buộc | Chặn export/job |
| Cảnh báo cần duyệt | Review item/conflict |
| Issue theo frame | Ground Truth conflict hoặc review frame |
| Người sửa annotation | Job assignee/reviewer |
| Nhiều annotator | Consensus replica |
| Quality metric | Quality report |
| Rework | Job stage/state hoặc review rejection |

Nếu issue của AutoQC cần lưu riêng để truy vết, có thể:

- Tạo API mới `/api/autoqc/runs`.
- Liên kết `AutoQcRun` với job/task.
- Liên kết `AutoQcIssue` với frame/shape.
- Sau khi apply, tạo quality report hoặc conflict tương ứng.

Không ghi thẳng issue machine vào annotation. Issue là dữ liệu quản trị,
annotation mới là dữ liệu nhãn.

## 9. Extension ngoài

Extension là UI tùy chọn. Nó nên có ba chức năng:

- Bấm **Run QC** để gửi yêu cầu worker.
- Hiển thị danh sách issue và mức priority.
- Mở frame/shape tương ứng trong CVAT.

Không nên để extension:

- Tải toàn bộ dataset.
- Chạy calibration.
- Tự đo duplicate bằng phash.
- Quyết định gate.
- Tự sửa annotation hàng loạt.

Extension có thể dùng trang panel bottom-left tương tự Face-50 và SAM 3,
nhưng không cần sửa CVAT React state.

## 10. Tích hợp sâu trong CVAT

Sau khi worker và API ổn định, có thể tích hợp trực tiếp:

- Thêm menu **Actions -> AutoQC** trong task/job.
- Thêm trang báo cáo trong `cvat-ui`.
- Tạo Django app `cvat/apps/autoqc`.
- Tạo API viewset cho runs/issues/review.
- Tạo RQ worker task.
- Gắn migration và permission với organization.
- Thêm quality report type hoặc tab riêng.

Đây là tích hợp dài hạn, không nên làm trước MVP.

## 11. MVP đề xuất

### Giai đoạn 1: Worker độc lập

- Nhận task/job ID qua token.
- Export frames và annotations.
- Chạy 4 module: format, duplicate, autofix và gate.
- Trả JSON report.
- Không ghi annotation tự động.

### Giai đoạn 2: Apply và review

- Cho phép apply fix an toàn.
- Ghi review log.
- Mở frame từ issue.
- Chạy lại QC sau khi sửa.

### Giai đoạn 3: Model checker

- Đưa YOLO26 hoặc model khác vào worker.
- Calibration `conf` và ngưỡng duplicate.
- Lưu prediction cache.

### Giai đoạn 4: Tích hợp sâu

- Thêm API/views trong CVAT backend.
- Thêm AutoQC tab trong UI.
- Liên kết report với task/job.
- Tự động tạo review/conflict.

## 12. API nội bộ đề xuất

```text
POST   /api/autoqc/runs
GET    /api/autoqc/runs/{id}
GET    /api/autoqc/runs/{id}/issues
POST   /api/autoqc/runs/{id}/apply
POST   /api/autoqc/runs/{id}/recheck
POST   /api/autoqc/runs/{id}/review
GET    /api/autoqc/runs/{id}/export
```

Ví dụ request:

```json
{
  "target": "job",
  "target_id": 42,
  "config": "configs/pipeline.yaml"
}
```

Ví dụ response:

```json
{
  "run_id": 17,
  "decision": "Hold",
  "n_images": 193,
  "n_errors": 0,
  "n_warn_images": 34,
  "warn_ratio": 0.1762
}
```

## 13. Rủi ro và cách giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Pipeline làm đổi nhãn ngoài ý muốn | Chỉ autofix lỗi đã định nghĩa; log before/after |
| Model checker báo động giả | Đưa issue vào review, không coi là ground truth |
| Calibration đánh lừa trên bộ nhỏ | Đánh giá trên calib riêng, ghi precision/recall/F1 |
| Annotation thay đổi giữa chừng | Lưu task/job/frame snapshot và run config hash |
| Tài nguyên batch không đủ | Dùng RQ worker, cache dự đoán, giới hạn batch |
| Phụ thuộc quá mạnh vào fork CVAT | Giữ AutoQC worker ngoài core, adapter CVAT riêng |
| Xung đột với Quality Control | Dùng issue riêng và liên kết sang quality report |

## 14. Các file cần tạo trong project

### MVP worker

```text
autoqc-server/
  app/
  cvat_adapter/
  pipeline/
  tests/
  Dockerfile
  requirements.txt
  README.md
```

### Tùy chọn extension

```text
autoqc-extension/
  manifest.json
  background.js
  content.js
  options.html
  options.js
  README.md
```

### Tài liệu

```text
guideline/AUTOQC_CVAT_INTEGRATION.md
```

## 15. Câu hỏi trước khi triển khai

Trước khi code, cần xác định:

1. AutoQC chạy ở task hay job level?
2. Ai được phép chạy và apply fix?
3. Fix nào được áp dụng tự động; fix nào bắt buộc người duyệt?
4. Report lưu trong database CVAT hay ngoài worker?
5. Release/Hold/Rework là trạng thái toàn task hay từng job?
6. Model có chạy theo từng frame hay batch?
7. Dataset clean xuất bằng định dạng nào: YOLO, COCO hay giữ CVAT format?

## 16. Khuyến nghị cuối

Tích hợp AutoQC theo hướng **worker độc lập + adapter CVAT + reuse Quality
Control**.

- Không cần bắt đầu bằng fork UI.
- Không cần sao chép hệ review của CVAT.
- Không nên dùng extension làm nơi chạy pipeline.
- Dùng extension sau nếu cần tiện ích duyệt trực tiếp.
- Chuyển sang Django/UI khi hệ thống cần nhiều task/job, quyền người dùng
  và trạng thái report lưu lâu dài.
