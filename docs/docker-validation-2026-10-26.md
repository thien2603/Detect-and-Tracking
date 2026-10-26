# Kiểm tra Docker thực tế — 26/10/2026

**Đã build và chạy đủ ba dịch vụ, kiểm tra chức năng thành công, dừng sạch.**
Đây là smoke test CPU; kết quả không thay bảng benchmark GPU 1/4/8 camera.

## Kết quả cuối

| Kiểm tra | Bằng chứng |
|---|---|
| Build image | `tracking-detection:local`, build exit 0; image ID `sha256:17ad035ad30c7f3e5fec5b02cc14236198bdc4213d1f7145b9e8ce980792e6b5`, 696993900 bytes. |
| Compose up | `app`, `replay`, `mediamtx` chạy đồng thời. |
| API health / cameras | Health `ok`, cả 4 camera xử lý YOLO và phát frame; lấy được 4 JPEG hợp lệ. |
| Bốn RTSP output | FFmpeg trên host giải mã được từng luồng qua cổng 18554. |
| Event / SQLite / snapshot | 11 sự kiện mới từ lúc container app bắt đầu trong cửa sổ kiểm tra cuối; có intrusion/region_entry, lọc theo camera/thời gian và snapshot JPEG hợp lệ. Đây không phải tổng đối tượng duy nhất. |
| Bật/tắt camera | Tắt một camera, ba camera còn lại vẫn tăng processed_frames; bật lại tạo session mới và có frame phát. |
| Lưu bằng chứng | `/health` cuối: `evidence_failed=0`. |
| Shutdown | Cả ba container `exited`, `ExitCode=0`, `OOMKilled=false`. Log app/replay xác nhận dừng worker, inference và publisher. |

Bằng chứng công khai trong repository:

- [Smoke JSON](verification/docker-20261026.json).
- [Shutdown JSON](verification/docker-shutdown-20261026.json).
- [JUnit toàn bộ](verification/pytest-20261026.xml).

Log, database, snapshot và lần thất bại được giữ local trong
`data/docker-validation-20261026-01/`. Các container test đã dừng; image và dữ liệu vẫn giữ.
Không dừng container của các dự án khác.

## Những vấn đề đã tìm thấy và sửa

1. Docker Desktop lỗi AF_UNIX socket `dockerInference`/`engine.sock` cũ.
   Đã đổi tên thư mục runtime để giữ backup rồi khởi động lại; không reset image/volume.
2. Bản Compose cũ chạy CPU với ảnh 640 và render đồng bộ. Dưới tải bốn camera,
   ảnh thường quá ngưỡng tuổi nên publisher bỏ, khiến RTSP client không decode được.
   Lần thất bại được giữ ở `smoke.json` và `default640-containers.log`.
3. Thêm `configs/docker-cpu.yaml`: ảnh model 320, FP32 CPU, async render,
   output tối đa 640×360, mục tiêu 10 FPS, replay 10 FPS. Giữ nguyên hình học và
   ngưỡng bỏ frame cũ **700 ms**, không nới latency để ép pass.
   Hộp dự đoán chỉ dùng vẽ; event vẫn từ detection thật.
4. Đặt `stop_signal: SIGINT` cho MediaMTX: lần đầu server thoát mã 2 khi dừng;
   sau thay đổi, thử lại cả ba container đều thoát mã 0.

Máy vẫn RAM 8 GB / Ryzen 5 6600H. Docker Engine 28.5.2, Compose 2.40.3;
container Python 3.12, PyTorch 2.14.1+cpu, Ultralytics 8.4.189, FFmpeg 5.1.9.
Lượt này dùng CPU/libx264, khác các lượt Windows CUDA/NVENC trong benchmark 23/10.
Không dùng nhịp render hoặc một frame decode để kết luận NFR ≥10 FPS và max latency <1 giây.

## Chạy lại trên máy đã có video và model

Thực hiện từ thư mục gốc repository, trong môi trường Python có dependency dự án.
Override tạo cổng API 18000/RTSP 18554 và database/snapshot/log riêng trong `data/docker-smoke`.

```powershell
docker compose --progress plain build app
docker compose -p tracking-docker-check -f docker-compose.yml -f configs/docker-smoke.compose.yaml up -d --no-build
python -m scripts.verify_docker --project tracking-docker-check --api http://127.0.0.1:18000 --rtsp rtsp://127.0.0.1:18554/processed --config configs/docker-cpu.yaml --ffmpeg C:\path\to\ffmpeg.exe --output data/docker-smoke/check-NEW.json
docker compose -p tracking-docker-check -f docker-compose.yml -f configs/docker-smoke.compose.yaml stop --timeout 45
```

Chọn output JSON mới mỗi lượt. Script cố ý từ chối ghi đè kết quả có sẵn và chỉ
chấp nhận event có thời gian từ lúc container app hiện tại bắt đầu.
