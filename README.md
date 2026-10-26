# Tracking Detection — mã nguồn đầy đủ

## Kết quả kiểm tra mới nhất — 26/10/2026

Mã nguồn đã có các nhóm chức năng F01–F10. Kiểm tra ngày 26/10: **94 test chính và
7 subtest đều pass**, không skip; Ruff pass. Docker đã build/up và kiểm tra thật:
bốn RTSP, API, sự kiện/snapshot, hot-toggle và ba container dừng mã 0.
Chạy test trong môi trường đã cài `.[inference,dev]`, có FFmpeg/MediaMTX.

- [Đối chiếu tiêu chí hiện tại](docs/criteria-audit-2026-10-26.md).
- [Báo cáo ngắn 4 trang](reports/TranDanhThien/BaoCao_TranDanhThien.pdf),
  [nguồn LaTeX](reports/TranDanhThien/main.tex).
- [Benchmark 1/4/8 camera](docs/benchmark-rerun-2026-10-23.md): 4 camera microbatch
  đạt trung bình 11,07 FPS ảnh mới/camera, nhưng max latency 1129 ms nên mới đạt
  độ trễ ở 3/4 camera. 8 camera chưa chạy thời gian thực.
- [Kiểm tra Docker và hướng dẫn chạy lại](docs/docker-validation-2026-10-26.md).
  Profile CPU dùng ảnh 320, render 640×360, mục tiêu 10 FPS; lượt này xác minh chức năng.
- Còn thiếu latency toàn bộ 4 camera, nghiệm thu webcam vật lý, VLC và upload Drive.

Các phần dưới giữ hướng dẫn và lịch sử triển khai; dùng bảng đối chiếu mới nhất
để xác định trạng thái nghiệm thu.

## Xem trực tiếp bốn camera

Sau khi chuẩn bị model/video, chạy ba dịch vụ trên cổng riêng và mở bảng xem:

```powershell
docker compose -p tracking-docker-check -f docker-compose.yml -f configs/docker-smoke.compose.yaml up -d --no-build
python -m scripts.view_cameras --api http://127.0.0.1:18000 --port 18001
```

Mở `http://127.0.0.1:18001` để xem bốn camera cùng bbox, ID, vạch và vùng.
Nếu chưa có image, chạy `docker compose build app` trước. Trình xem chỉ bind
localhost và chỉ đọc ảnh/trạng thái API; không khởi tạo thêm model.
Trang lấy JPEG khoảng 2 lần/giây để giảm tải, khác FPS detect và FPS RTSP.
Nút tạm dừng chỉ dừng cập nhật trang. Dừng viewer bằng Ctrl+C; dừng camera bằng:

```powershell
docker compose -p tracking-docker-check -f docker-compose.yml -f configs/docker-smoke.compose.yaml stop --timeout 45
```

Bản dựng lại 0.2.0, ngày 20/10/2026. Đây là mã nguồn được tạo lại sau khi workspace
cũ bị đặt lại, không phải bản khôi phục byte-for-byte của ZIP cũ. Repository chỉ lưu
mã nguồn, cấu hình, tài liệu và tests; model, video/dataset và kết quả sinh ra không
được đưa lên GitHub. Dùng các script tải dữ liệu/model bên dưới để chuẩn bị khi chạy.

Chức năng: YOLO11 nhận diện ô tô, tracker IoU gán ID riêng cho từng camera, vệt di chuyển,
đường đếm hai chiều, vùng cảnh báo đa giác, ảnh sự kiện, SQLite, JSON, FastAPI và đầu ra RTSP.
Một model dùng chung được điều phối bởi hàng đợi công bằng có giới hạn. Mỗi camera có
buffer một frame mới nhất. Video cao tốc dùng lịch vùng theo thời gian cho camera di chuyển.

## Lấy mã nguồn trên Windows

Clone repository bằng PowerShell:

```powershell
$dest = 'D:\MyWork\Tracking_Detection'
git clone https://github.com/thien2603/Detect-and-Tracking.git $dest
Set-Location $dest
```

## Cài đặt trên Windows

Cần Python **3.12** và FFmpeg có cả `ffmpeg` lẫn `ffprobe` trong PATH.
Có thể cài FFmpeg bằng `winget install --id Gyan.FFmpeg -e`, sau đó mở lại PowerShell.
Script setup mặc định cài PyTorch CPU. GPU cần bản PyTorch phù hợp CUDA của máy.

```powershell
Set-Location 'D:\MyWork\Tracking_Detection'
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pytest
```

Nếu không dùng script:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[inference,dev]"
```

## Tải model, tải video và xuất kết quả

```powershell
.\.venv\Scripts\python.exe -m scripts.download_model
.\.venv\Scripts\python.exe -m scripts.download_expressway
.\.venv\Scripts\python.exe -m scripts.render_video --config configs/vietnam-expressway.yaml
```

Hoặc: `powershell -ExecutionPolicy Bypass -File .\scripts\run_expressway.ps1 -Download`.
Chạy lại mà không tải: bỏ `-Download`.

Video tải từ trình phát công khai của bài VietNamNet được ghi trong `docs/dataset.md`.
Video gốc đã kiểm tra ở phiên trước dài 125,8 giây. Script kiểm tra thời lượng 120–180 giây;
nếu nhà xuất bản đổi nguồn hoặc chặn truy cập, script báo lỗi. Không lặp hoặc làm chậm để kéo dài.
Nguồn có ô tô con, xe khách, xe tải; cấu hình **chỉ xử lý lớp `car`**.

Kết quả:

```text
data/vietnam-expressway-tracking.mp4             Video có ID và vùng cảnh báo
data/vietnam-expressway-tracking.events.json     Nhật ký theo thời gian video
data/vietnam-expressway-tracking.db              SQLite của lần chạy offline
data/vietnam-expressway-tracking-snapshots/      Ảnh sự kiện
```

Offline xử lý toàn bộ frame được lấy mẫu tại FPS đầu ra; thời gian xử lý có thể lâu hơn video.
`--fps 10` mặc định, `--max-seconds 10` để chạy thử. Nguồn có FPS thấp hơn sẽ giữ FPS nguồn.
Nguồn phải có kích thước chẵn để mã hóa H.264/yuv420p.

## Chạy API

```powershell
$env:CONFIG_PATH = 'configs/vietnam-expressway.yaml'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/docs`. Dừng bằng Ctrl+C. File source được phát theo tốc độ video,
khác với renderer offline. API không tự sinh một file MP4 đầy đủ; dùng renderer để lưu video.

| Endpoint | Chức năng |
|---|---|
| `GET /health` | Trạng thái ứng dụng và số sự kiện bị bỏ/lưu lỗi |
| `GET /api/v1/cameras` | Trạng thái, ID phiên, FPS, số frame và lỗi từng camera |
| `PUT /api/v1/cameras/{id}/enabled` | Bật/tắt; JSON `{"enabled": true}` hoặc `false` |
| `GET /api/v1/cameras/{id}/frame.jpg` | Frame đã xử lý gần nhất |
| `GET /api/v1/events` | Lọc theo `camera_id`, `start`, `end`, `limit` |
| `GET /api/v1/events/{id}/snapshot` | Ảnh sự kiện |

Thời gian lọc sự kiện là thời gian chạy máy theo UTC, không phải thời điểm ghi hình năm 2024.
`video_seconds` là số giây tính từ đầu video. Khoảng thời gian ISO không có múi giờ được hiểu UTC.
API chưa có xác thực; chạy trên `127.0.0.1` khi dùng trên máy cá nhân.

## Nhiều camera và RTSP

`configs/config.yaml` mặc định giống cấu hình cao tốc để chạy ngay sau khi tải dữ liệu.
`configs/four-cameras.yaml` là cấu hình mẫu 4 file, cần tự cung cấp video vào
`data/videos/traffic/camera_01.mp4` … `camera_04.mp4`, hoặc sửa nguồn thành:

```yaml
source:
  type: rtsp
  uri: rtsp://your-camera-host/stream
  loop: false
```

Mỗi camera cố định cần hiệu chỉnh ROI/đường đếm/vùng theo chính góc quay đó.
Không áp lịch vùng của clip cao tốc cho camera khác. Cấu hình mẫu 4 camera không tự tạo vùng cấm.

Để phát RTSP, khởi động MediaMTX bằng Docker Compose hoặc bản MediaMTX cho Windows.
Đặt `streaming.enabled: true`; đầu ra: `rtsp://localhost:8554/processed/<output_path>`.
Với Compose, đặt host RTSP trong mạng container là `mediamtx`, đã có ở `configs/docker.yaml`.

```powershell
# Chuẩn bị video/model trước bằng các lệnh phía trên
docker compose up --build
```

Compose gồm `mediamtx`, `replay` và `app`: replay phát bốn file cấu hình trong
`configs/docker-cpu.yaml` thành RTSP, app nhận và xử lý. Model và dữ liệu
được mount từ máy chủ. Dockerfile dùng CPU; đã build/up, kiểm tra API, bốn RTSP,
event/snapshot và shutdown trên máy Windows ngày 26/10. Profile GPU benchmark
được giữ riêng, không lấy lượt smoke CPU thay cho benchmark. Chỉ chạy một worker Uvicorn.

## Cấu trúc và cách sửa

Xem `docs/file-structure.md` để biết vai trò từng file, `docs/vietnam-expressway.md` để chỉnh vùng,
và `docs/validation.md` để biết các kiểm tra thực tế của bản này.

```text
app/             Mã nhận diện, tracking, camera, quy tắc, API và streaming
configs/         Cấu hình nguồn, model, lịch vùng
scripts/         Tải dữ liệu/model, render, xem vùng, setup Windows, smoke test
tests/           Kiểm thử hồi quy và tích hợp bằng detector giả
benchmarks/      Lấy mẫu số liệu API; không phải kết quả đo sẵn
infrastructure/  Cấu hình MediaMTX
docs/            Tài liệu, nguồn và giới hạn
models/          Model .pt được tải riêng
data/            Video, JSON, SQLite, snapshots được tạo khi chạy
logs/            Log có xoay vòng
```

Repository không chứa môi trường `.venv`, cache, database, log, model, video hoặc
kết quả sinh ra. Có đầy đủ mã để tải dữ liệu/model và tạo lại kết quả.

## Linux/macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e '.[inference,dev]'
python -m scripts.download_model
python -m scripts.download_expressway
python -m scripts.render_video
python -m pytest
python -m ruff check app scripts tests benchmarks
```

Trên macOS hãy cài PyTorch theo hướng dẫn chính thức cho nền tảng thay vì CPU wheel index Linux.

## Giới hạn

Đợt bổ sung cho Trần Danh Thiện: [thay đổi, kiểm thử, dữ liệu người và hồ sơ nộp](docs/supplement-2026-10-22.md).
Config 4 nguồn có cả người: `configs/submission-four.yaml`; cấu hình thử tiết kiệm
tài nguyên: `configs/submission-efficient.yaml`. Bốn config Bellevue cũ được giữ nguyên.

Hướng dẫn service RTSP bốn camera, benchmark và trạng thái kiểm tra thực tế:
[Chạy realtime và benchmark](docs/realtime-and-benchmark.md). Lượt đo mới ngày 23/10
đạt unique output ≥10 FPS ở cả bốn camera nhưng còn thiếu latency: microbatch chỉ
3/4 camera có max <1 giây. Xem [số liệu mới](docs/benchmark-rerun-2026-10-23.md).

- Tracker IoU có thể đổi ID khi che khuất, bỏ sót hoặc xe chuyển động nhanh. Chưa có đánh giá IDF1/MOTA.
- `entry`: đã quan sát cùng ID bên ngoài rồi vào vùng. `first_seen_inside`: lần đầu thấy đã trong vùng.
- Không nhận dạng biển số, không đo vận tốc thật, không tự kết luận vi phạm giao thông.
- Vùng camera di chuyển được nội suy từ các mốc hiệu chỉnh thủ công, có sai số.
- FPS encode có thể gồm frame lặp khi tốc độ phát RTSP cao hơn inference. API tách số frame đầu ra
  và số frame mới. `internal_latency_ms` chỉ đo thời gian nội bộ, không phải độ trễ camera đến màn hình.
- Hàng đợi lưu ảnh có giới hạn, theo dõi `evidence_dropped` và `evidence_failed` ở `/health`.

## Tối ưu realtime (22/10/2026)

Pipeline bất đồng bộ, dự đoán Kalman có hạn, FP16 CUDA và encoder NVENC có CPU
fallback: xem [hướng dẫn và cách đo](docs/optimization-2026-10-22.md).
Cấu hình gốc và kết quả benchmark trước vẫn được giữ để đối chứng.

Đã có [đối chứng 60 giây trên 4 camera](docs/optimization-results-2026-10-23.md):
video mới hơn11 FPS/camera, nhưng YOLO thật2,67–3,02 FPS/camera; xem đầy đủ giới hạn
tracking, tuổi detection và CPU trước khi dùng kết quả để kết luận đạt yêu cầu.

Có thêm chế độ4camera/4model độc lập và tùy chọn CUDA stream riêng. Xem
[cách chạy và đối chứng các chế độ model](docs/model-modes-2026-10-23.md).
Mặc định vẫn giữ model dùng chung; không tự chuyển sang nhiều model.
