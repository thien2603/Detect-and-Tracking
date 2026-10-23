# Đối chứng tiêu chí cuối — 23/10/2026

Tác giả: **Trần Danh Thiện**  
GitHub do người dùng cung cấp: <https://github.com/thien2603/Detect-and-Tracking.git>

Tài liệu này chỉ đánh dấu theo bằng chứng đã chạy. Không dùng việc “có mã” để thay cho kiểm thử, và không dùng frame lặp để chứng minh FPS xử lý.

## Chức năng F01–F10

| Mã | Trạng thái | Bằng chứng/giới hạn |
|---|---|---|
| F01 nguồn file/RTSP/webcam, reconnect, cô lập lỗi | Đạt mã + test tích hợp; còn thiếu webcam vật lý | Capture hỗ trợ ba loại. Test MediaMTX/FFmpeg thật xác nhận ngắt một nguồn, ba nguồn khác tiếp tục và nguồn lỗi reconnect. Chưa có thiết bị webcam thật để nghiệm thu. |
| F02 latest-frame, không dồn queue | Đạt | Capture giữ latest slot, scheduler/publisher queue hữu hạn; unit/integration test đã qua. |
| F03 YOLOv8+, người và xe, cấu hình class/conf/imgsz | Đạt | YOLO11n CUDA; video người thật được lấy mẫu bằng model thật, có person/car/bus/truck; YAML điều khiển class/conf/imgsz. |
| F04 tracking ID theo camera | Đạt cơ bản | Tracker độc lập/camera, test giữ ID sau bỏ sót ngắn. IoU/Kalman không phải bằng chứng độ chính xác khi che khuất/chuyển động rất nhanh. |
| F05 vạch hữu hạn, hai chiều | Đạt | Unit test deadband/finite segment/cooldown; event `line_crossing` và HUD hai chiều có trong chạy thật. |
| F06 polygon cấm, ngoài→trong | Đạt | Unit test và event `intrusion`; không lặp khi đứng trong vùng. |
| F07 event duy nhất, SQLite, snapshot | Đạt theo track/event ID | Timestamp/camera/track/type/snapshot đầy đủ; retry cùng event ID không chèn trùng. Không coi đây là chống đếm lại cùng xe vật lý nếu tracker đổi ID. |
| F08 bbox/ID/line/zone/count, RTSP riêng, FFmpeg restart | Đạt mã + integration; thiếu VLC GUI | Bốn RTSP output thật, annotation và publisher restart đã kiểm thử. Chưa mở/ghi nhận thủ công đủ bốn URL bằng VLC GUI. |
| F09 YAML, fail-fast, thêm camera chỉ sửa config | Đạt | Preflight weights/classes/device/FFmpeg/schedule/URL; wrapper lấy mọi camera YAML. |
| F10 FastAPI status/FPS, enable/disable, lọc event | Đạt test | TestClient/repository và status chạy thật đã xác minh. |

## Phi chức năng và benchmark

| Tiêu chí | Trạng thái | Bằng chứng mới nhất |
|---|---|---|
| 4 camera đồng thời | Đạt vận hành | Demo 120 giây và benchmark 4 camera đều chạy bốn pipeline đồng thời. |
| Output >=10 FPS/camera | Đạt ở 4 camera trong lượt mới | `serial`: 4/4; `batch`: 4/4 theo `unique_source_fps`. |
| Latency đầu-cuối <1 giây ở 4 camera | **Chưa đạt hoàn toàn** | `serial`: 1/4; `batch`: 3/4. Max xấu nhất lần lượt 1091 ms và 1129 ms. |
| 1/4/8 camera, ít nhất hai chiến lược | Đạt yêu cầu đo | Đã đo đủ 6 tổ hợp serial/batch, 60 giây/tổ hợp. 8 camera không đạt thời gian thực nhưng kết quả thất bại được giữ nguyên. |
| Chọn kiến trúc bằng dữ liệu | Đạt | Chọn shared micro-batch: ở 4 camera detect FPS 3,05 so với 1,14; CPU 646% so với 702%; latency pass 3/4 so với 1/4. |
| Ctrl+C/cleanup sạch | Đạt bằng chứng cleanup | Các lượt hoàn tất có `cleanup.json`; demo 120 giây có service/replay true và không còn descendant. |
| Logging file, FPS/latency/reconnect | Đạt | Service dùng logging; không dùng `print` trong app/scripts/benchmarks. |
| Unit test line/zone và suite | Đạt | 101 JUnit testcase, 0 failure/error/skip; Ruff đã qua ở lần xác minh cuối. |
| Docker | **Một phần** | Compose parse qua. Đã sửa Docker Desktop 4.51.0 và xác minh Engine 28.5.2 chạy thật. Chưa build/run stack project: Docker/WSL làm RAM trống giảm từ khoảng 2.057 MiB xuống 423 MiB nên build PyTorch bị dừng để tránh treo máy. |

Chi tiết số đo: [benchmark-rerun-2026-10-23.md](benchmark-rerun-2026-10-23.md).

## Bộ nộp

| Hạng mục | Trạng thái |
|---|---|
| `BaoCao_TranDanhThien.pdf` | Có, 10 trang, đã cập nhật bảng benchmark ngày 23/10, compile và render kiểm tra. |
| `Demo_TranDanhThien.mp4` | Có, khoảng 120 giây, 4 camera đồng thời, decode toàn bộ không lỗi. |
| Link GitHub | Có URL do người dùng cung cấp, nhưng **chưa xác minh source local hiện tại đã push**. |
| Google Drive/thư mục `TranDanhThien` | **Chưa upload/xác minh quyền truy cập**. |

## Những mục còn thiếu trước khi tuyên bố “đủ toàn bộ”

1. Giảm latency camera xấu nhất của cấu hình 4-camera batch từ 1.129 ms xuống dưới 1.000 ms trong một phép đo lại cùng điều kiện.
2. Build và chạy thật stack project bằng Docker; kiểm tra API, RTSP, event và shutdown container. Máy 8 GB hiện không đủ RAM an toàn khi đồng thời mở Docker Desktop và build image PyTorch.
3. Nghiệm thu webcam vật lý nếu giảng viên bắt buộc kiểm tra cả ba loại nguồn, và mở bốn output bằng VLC GUI.
4. Xác minh commit/source hiện tại đã push lên GitHub; upload PDF/MP4 vào Drive đúng tên và kiểm tra quyền xem.
5. Nếu cần tuyên bố độ chính xác, phải gán nhãn ground truth và tính precision/recall, ID switches và sai số đếm. Benchmark hiện chỉ chứng minh hiệu năng, không chứng minh accuracy.

## Đường dẫn bằng chứng chính

- `data/benchmark-rerun-20261023-01/benchmark.json` — 1 camera serial/batch.
- `data/benchmark-rerun-20261023-4-8-02/benchmark.json` — 4/8 camera serial/batch, status completed.
- `data/benchmark-rerun-20261023-4-8-01/benchmark.json` — preflight RAM bị chặn, được giữ làm bằng chứng.
- `output/final-submission/TranDanhThien/Demo_TranDanhThien.mp4` — demo 120 giây.
- `output/final-submission/TranDanhThien/BaoCao_TranDanhThien.pdf` — báo cáo hiện hành.

