# Benchmark rerun — 23/10/2026

## Phạm vi

- Máy: Lenovo Legion 5 15ARH7, Ryzen 5 6600H (6C/12T), RAM khả dụng 7.365 MiB, RTX 3050 Laptop 4 GiB.
- Mô hình: YOLO11n, CUDA, FP16, `imgsz=480`, detect interval 2.
- Output: RTSP H.264 NVENC, mục tiêu 14 FPS, render bất đồng bộ và Kalman chỉ dùng cho hiển thị.
- Mỗi kịch bản đo 60 giây sau warm-up 8 giây.
- Hai chiến lược: `serial` (batch size 1) và `batch` (micro-batch tối đa 4).
- `unique_source_fps` là số ảnh nguồn khác nhau giải mã được từ RTSP output; đây là số dùng để xét ngưỡng 10 FPS.
- Latency đo từ marker của file replay tới frame RTSP output được giải mã trên cùng máy; tiêu chí là max < 1.000 ms với coverage >= 95%.

## Kết quả

| Camera | Chiến lược | Detect FPS TB/cam | Unique output FPS TB/cam | P95 cao nhất (ms) | Max cao nhất (ms) | Đạt >=10 FPS | Đạt latency | CPU tổng TB | Peak RSS | Peak GPU | RAM trống thấp nhất |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | serial | 6,48 | 12,55 | 593 | 639 | 1/1 | 1/1 | 133% | 1.555 MiB | 254 MiB | 442 MiB |
| 1 | batch | 6,52 | 12,38 | 600 | 723 | 1/1 | 1/1 | 129% | 2.036 MiB | 276 MiB | 371 MiB |
| 4 | serial | 1,14 | 10,52 | 756 | 1.091 | 4/4 | 1/4 | 702% | 1.964 MiB | 505 MiB | 498 MiB |
| 4 | batch | 3,05 | 11,07 | 754 | 1.129 | 4/4 | 3/4 | 646% | 2.583 MiB | 527 MiB | 276 MiB |
| 8 | serial | 0,17 | 0,91 | 8.081 | 10.191 | 0/8 | 0/8 | 840% | 1.426 MiB | 649 MiB | 663 MiB |
| 8 | batch | 0,37 | 0,98 | 5.102 | 7.277 | 0/8 | 0/8 | 878% | 1.582 MiB | 688 MiB | 529 MiB |

## Kết luận

1. Một camera đạt cả output >=10 FPS và latency <1 giây ở hai chiến lược.
2. Bốn camera đạt output >=10 FPS/camera ở cả hai chiến lược, nhưng không đạt đồng thời latency max <1 giây cho mọi camera. `batch` đạt 3/4 camera về latency, tốt hơn `serial` chỉ đạt 1/4.
3. Tám camera vượt khả năng thời gian thực của máy: output duy nhất chỉ khoảng 0,9–1,0 FPS/camera và latency max 7,3–10,2 giây.
4. Chọn `batch` làm cấu hình chính vì ở 4 camera detect FPS trung bình tăng từ 1,14 lên 3,05 FPS/camera, CPU giảm từ 702% xuống 646%, và số camera đạt latency tăng từ 1/4 lên 3/4.
5. Tiêu chí phi chức năng 4 camera >=10 FPS và latency <1 giây hiện chỉ đạt phần FPS; phần latency vẫn thiếu 1 camera trong lần đo mới nhất.

## Bằng chứng

- `data/benchmark-rerun-20261023-01/benchmark.json`: hai kết quả 1 camera hoàn chỉnh. Phiên điều khiển bị ngắt sau đó nên trường status cấp gốc chưa được ghi, nhưng từng measurement 1 camera có đủ 60 giây và `status=completed`.
- `data/benchmark-rerun-20261023-4-8-01/benchmark.json`: lần thử 4/8 bị preflight chặn vì chỉ còn 287 MiB RAM sau khi nạp Python/OpenCV/Torch; không tạo số liệu giả.
- `data/benchmark-rerun-20261023-4-8-02/benchmark.json`: bốn kết quả 4/8 camera hoàn chỉnh, status `completed`.
- Mỗi thư mục kịch bản có `measurement.json`, `cleanup.json`, log API/MediaMTX/replay/service, database sự kiện và snapshot.

