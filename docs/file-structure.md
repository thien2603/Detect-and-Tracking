# Cấu trúc và vai trò từng file

## Luồng xử lý

```text
Video/RTSP/webcam → capture.py → scheduler.py → detector.py
                                                    ↓
                                             pipeline.py
                                                    ↓
                            region.py → tracker.py → quy tắc sự kiện
                                                    ↓
                              annotator.py → ảnh / RTSP / video MP4
                                                    ↓
                            repository.py → SQLite + snapshots (+ JSON offline)
```

## Các thành phần

| File | Chức năng |
|---|---|
| `app/main.py` | FastAPI, vòng đời ứng dụng, endpoint camera/sự kiện/snapshot |
| `app/manager.py` | Tạo/dừng worker, bật/tắt camera, thu thập số liệu |
| `app/pipeline.py` | Luồng quy tắc dùng chung offline và live, lịch vùng, vệt xe |
| `app/config/schemas.py` | Kiểu cấu hình Pydantic, kiểm tra đầu vào |
| `app/config/loader.py` | Đọc YAML, giải đường dẫn theo gốc dự án, kiểm tra file |
| `app/camera/capture.py` | Đọc nguồn, buffer frame mới nhất, reconnect và pacing file |
| `app/inference/types.py` | Dữ liệu Detection và Track, điểm anchor cạnh đáy |
| `app/inference/detector.py` | Nạp YOLO, đổi tên lớp sang COCO ID, suy luận |
| `app/inference/scheduler.py` | Một model thread, hàng đợi tối đa một yêu cầu chờ/camera |
| `app/inference/tracker.py` | Ghép khung bằng IoU và lớp, tạo/xóa ID |
| `app/inference/region.py` | Lọc bbox ngoài ROI trước khi tracking |
| `app/events/geometry.py` | Điểm trong đa giác, khoảng cách có dấu, giao đường đếm hữu hạn |
| `app/events/intrusion.py` | Trạng thái trong/ngoài vùng, entry và first_seen_inside |
| `app/events/line_counter.py` | Đếm hai hướng, deadband chống rung và cooldown |
| `app/events/schedule.py` | Kiểm tra lịch vùng, chọn cảnh, nội suy keyframe |
| `app/events/processor.py` | Gom kết quả quy tắc thành EventCandidate |
| `app/events/types.py` | Cấu trúc sự kiện, UUID, thời gian UTC và thời gian video |
| `app/events/repository.py` | SQLite WAL, ảnh JPEG, hàng đợi ghi chứng cứ có giới hạn |
| `app/streaming/annotator.py` | Vẽ ID, vệt xe, đường đếm, vùng đỏ và footer |
| `app/streaming/publisher.py` | FFmpeg RTSP, buffer một frame, watchdog cho ghi bị treo |

Mỗi `__init__.py` đánh dấu thư mục là package Python; không phải một chương trình cần chạy riêng.

## Cấu hình

| File | Chức năng |
|---|---|
| `configs/config.yaml` | Mặc định một video cao tốc, giống vietnam-expressway.yaml |
| `configs/vietnam-expressway.yaml` | Chỉ class car; file cao tốc và lịch vùng tương ứng |
| `configs/vietnam-expressway-zones.json` | Tọa độ vùng trên ảnh 640x360 theo thời gian |
| `configs/four-cameras.yaml` | Mẫu bốn file/camera cố định, cần bổ sung nguồn |
| `configs/docker.yaml` | Cao tốc, bật RTSP với host nội bộ mediamtx |
| `infrastructure/mediamtx.yml` | Cấu hình máy chủ RTSP |

## Công cụ

| File | Chức năng |
|---|---|
| `scripts/download_model.py` | Tải trọng số Ultralytics chính thức |
| `scripts/download_expressway.py` | Đọc trình phát công khai, tải và chuẩn hóa video |
| `scripts/render_video.py` | Xuất MP4 đầy đủ và JSON/SQLite/snapshots |
| `scripts/preview_regions.py` | Kiểm tra vùng và detection tại một mốc video |
| `scripts/smoke_test.py` | Đọc health/cameras/events của API đang chạy |
| `scripts/start.sh` | Chạy API trên Linux/macOS |
| `scripts/setup.ps1` | Tạo venv và cài thư viện trên Windows |
| `scripts/run_expressway.ps1` | Tải tùy chọn, render hoặc chạy API Windows |
| `benchmarks/monitor.py` | Lấy mẫu số liệu API theo thời gian |

Chạy công cụ Python từ gốc dự án bằng `python -m scripts.<tên_không_có_py>`.
Không cần đặt thủ công PYTHONPATH.

## Kiểm thử và tài liệu

`tests/conftest.py`: video tổng hợp và fixture. `tests/test_rules.py`: hình học,
IoU, trạng thái vùng, lịch vùng và đếm xe. `tests/test_service.py`: cấu hình, pipeline,
scheduler, SQLite, API và render MP4 bằng FFmpeg. Detector giả kiểm tra logic, không
thay thế việc đánh giá model trên dữ liệu đã gán nhãn.

`docs/dataset.md`: nguồn dữ liệu. `docs/vietnam-expressway.md`: quy tắc vùng và giới hạn.
`docs/validation.md`: kết quả kiểm tra của bản dựng lại. `README.md`: hướng dẫn chạy.
`pyproject.toml`: dependencies và cấu hình test/lint. `Dockerfile`/`docker-compose.yml`:
đóng gói chạy container. `Makefile`: lệnh tắt. `.gitignore`/`.dockerignore`: loại file
tự sinh khỏi Git/image. `.env.example`: ví dụ biến môi trường; ứng dụng đọc biến đã export,
không tự nạp file `.env` trong lệnh Uvicorn trực tiếp.

## File sinh khi chạy

`models/yolo11n.pt`: trọng số đã huấn luyện, không phải mã nguồn Python.
`data/videos/vietnam-expressway/highway-126s.mp4`: nguồn chuẩn hóa.
File `.source.json` cạnh video lưu nguồn và hash.
Renderer tạo `.mp4`, `.events.json`, `.db` và thư mục `-snapshots`.
API tạo database/ảnh theo YAML. `logs/` chứa nhật ký xoay vòng.

Thư mục `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `*.egg-info` là
file môi trường/cache tự sinh, không cần gửi cùng mã nguồn. `.gitkeep` giữ các thư mục
dữ liệu/model/log trống trong gói source.
