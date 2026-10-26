# Đối chiếu yêu cầu — 26/10/2026

Kết luận: **chưa đủ căn cứ xác nhận đạt toàn bộ đề**. Các nhóm chức năng đã có mã
và kiểm thử; Docker đã build/up và kiểm tra thực. Còn thiếu độ trễ 4 camera và webcam/VLC.
Thư mục Drive chưa được xác minh. Đối chiếu theo đề `TTS_Tuan1.pdf` do người dùng cung cấp.

## Chức năng

| Mã | Kết quả | Mã nguồn / bằng chứng |
|---|---|---|
| F01 | Có hỗ trợ; còn thiếu webcam vật lý | `app/camera/capture.py`: file/RTSP/webcam; integration test ngắt nguồn, reconnect, ba nguồn khác tiếp tục. |
| F02 | Có bằng chứng | Latest-frame slot, scheduler pending/camera, publisher queue hữu hạn; test thay request cũ. |
| F03 | Có bằng chứng | `app/inference/detector.py`, YOLO11n; class/conf/imgsz từ YAML; video người và xe đã chạy YOLO thật. |
| F04 | Có bằng chứng | `tracker.py`, `motion.py` trong `app/inference/`; ID riêng/camera, IoU/Kalman. |
| F05 | Có bằng chứng | `app/events/line_counter.py`; hai chiều, đoạn hữu hạn, deadband/cooldown; unit test và event demo. |
| F06 | Có bằng chứng | `app/events/intrusion.py`, `geometry.py`; test entry/stay/exit/reentry và biên polygon. |
| F07 | Có bằng chứng theo track/event ID | SQLite, UTC/camera/track/type/snapshot; test retry đồng thời chỉ ghi một bản. Tracker đổi ID vẫn có thể đếm lại vật thể. |
| F08 | Có code và integration; còn VLC GUI | `annotator.py`, `publisher.py` trong `app/streaming/`; output RTSP decode thật, test FFmpeg restart. |
| F09 | Có bằng chứng | YAML/schema/preflight; test fail-fast và thêm nguồn bằng config. |
| F10 | Có bằng chứng | `app/main.py`; API status/FPS, hot-toggle, events theo camera/thời gian, snapshot; test pass. |

## Phi chức năng và hồ sơ

| Yêu cầu | Kết quả |
|---|---|
| 4 camera đồng thời, mỗi camera ≥10 FPS | Đạt unique output FPS ở cả hai chiến lược trong lượt đo 23/10; không đồng nghĩa YOLO ≥10 FPS. |
| Trễ đầu-cuối <1 giây | Chưa đạt toàn bộ: microbatch chỉ 3/4 camera; max 1129 ms. Đo replay→RTSP decoder, chưa đo tới VLC. |
| Ctrl+C dừng sạch | Có cleanup từ demo/benchmark; integration test mới cũng kiểm tra thread/scheduler dừng. |
| Logging file, FPS/trễ/reconnect | Có mã logging xoay vòng và số liệu theo camera; không có `print()` trong app/scripts/benchmarks. |
| Unit test vạch/vùng | Đạt: thuộc bộ test đầy đủ ngày 26/10. |
| Docker | **Đã chạy thực**: build/up ba dịch vụ, 4 RTSP decode, API/event/snapshot/filter/hot-toggle pass. Cả ba container thoát mã 0, không OOM. Dùng profile CPU 320; chưa coi là benchmark NFR. |
| Benchmark 1/4/8, ít nhất hai cách | Đủ sáu tổ hợp serial/microbatch, 60 giây/lượt; có thêm so sánh model chung/4 model/4 CUDA stream. Đề yêu cầu đo 8 camera, không yêu cầu 8 camera đạt 10 FPS. |
| Chọn kiến trúc theo số liệu | Chọn shared microbatch; xem bảng benchmark. |
| GitHub | Đã push bản `5c6b843`; cấu hình và bằng chứng Docker được bổ sung trong lần cập nhật tiếp theo. |
| Báo cáo | Đã rút từ 10 xuống 4 trang; có link source, benchmark, nhận xét và mục còn thiếu. |
| Demo | File local 120 giây, bốn nguồn đồng thời; 391 sự kiện trong cửa sổ ghi; đã kiểm tra giải mã. |
| Google Drive | Chưa upload/xác minh thư mục `TranDanhThien` và quyền truy cập. |

## Kiểm tra thực hiện lại ngày 26/10

- **94 test chính + 7 subtest pass, không failure/error/skip**, chạy lại sau sửa Docker: 88,43 giây.
- Ruff: `check app scripts tests benchmarks` pass.
- `docker compose config --quiet`: exit 0; lệnh này không chứng minh container đã chạy.
- Sau đó đã build/up và chạy smoke thật: `docs/verification/docker-20261026.json`;
  shutdown ba container mã 0: `docs/verification/docker-shutdown-20261026.json`.
  Chi tiết: [Docker validation](docker-validation-2026-10-26.md).
- JUnit cuối: `data/docker-validation-20261026-01/tests-final.xml`; bản lưu trong repository:
  `docs/verification/pytest-20261026.xml`.
- Dùng `.tools/bellevue-env` có `httpx2`, `pytest-timeout`, Ruff; FFmpeg 7.1 và MediaMTX 1.9.3.
- Test API ban đầu treo trong sandbox tại `socket.socketpair()` của asyncio Windows;
  chạy cùng bộ test ngoài sandbox đã pass. Không phải bằng chứng lỗi ứng dụng.

Lệnh tái lập sau khi cài dependency dev, FFmpeg/MediaMTX:

```powershell
$env:FFMPEG_TEST_BIN = 'C:\path\to\ffmpeg.exe'
$env:MEDIAMTX_TEST_BIN = 'C:\path\to\mediamtx.exe'
python -m pytest --timeout=90 --junitxml=tmp/pytest.xml
python -m ruff check app scripts tests benchmarks
docker compose config --quiet
```

Các test hạ tầng dùng detector giả; benchmark hiệu năng dùng YOLO thật.
Chưa có ground truth để công bố precision/recall/sai số đếm; đề không yêu cầu
ngưỡng accuracy cụ thể nên đây là giới hạn chất lượng, không thêm một tiêu chí bắt buộc.

## Cần hoàn tất

1. Giảm latency của camera còn lại xuống dưới 1000 ms, đo lại cùng điều kiện.
2. Thử webcam thật và mở bốn RTSP bằng VLC.
3. Upload báo cáo/demo vào Drive đúng tên, xác minh quyền xem.

Số liệu đầy đủ: [benchmark 23/10](benchmark-rerun-2026-10-23.md).
Báo cáo: [PDF 4 trang](../reports/TranDanhThien/BaoCao_TranDanhThien.pdf),
[LaTeX](../reports/TranDanhThien/main.tex).
