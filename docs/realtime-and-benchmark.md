# Chạy realtime và đo đúng yêu cầu bài thực tập

> Tài liệu này giữ thông tin các lần thử đầu. Xem [bản bổ sung mới](supplement-2026-10-22.md)
> cho startup preflight, video người, ma trận benchmark và hồ sơ Trần Danh Thiện.

## Những phần đã bổ sung

- Cấu hình Bellevue có `person`, `car`, `motorcycle`, `bus`, `truck`.
- Mỗi camera có vạch đếm hai chiều bên cạnh vùng xanh 75% và zone đỏ 25% đã duyệt.
- Cấu hình RTSP riêng: `configs/bellevue-realtime.yaml`.
- Cấu hình Docker 4 camera: `configs/bellevue-docker.yaml`; Compose có MediaMTX,
  nguồn phát lại và service xử lý. Không còn dùng một video cao tốc làm demo Docker.
- Capture thử lại cả khi mở/đọc RTSP phát sinh ngoại lệ; có số lần mở và reconnect.
- Log định kỳ FPS detect, số frame xuất, frame mới, độ trễ nội bộ, reconnect,
  lỗi publisher và số lần FFmpeg khởi động lại.
- `benchmarks.run` thực thi ma trận 1/4/8 camera với hai chiến lược: một-frame/lần
  (`serial`, batch=1) và microbatch dùng chung model (`batch`, batch=4, chờ tối đa 5 ms).
- Có kiểm tra bộ nhớ trước khi tải YOLO; không ghi kết quả giả khi thiếu RAM.
- Kiểm tra API bằng TestClient đã qua khi cho phép socket loopback. Lần treo trong
  sandbox xảy ra khi Python tạo socketpair, trước khi ứng dụng bắt đầu chạy.

## Cài đặt chuẩn

Python 3.10 trở lên, FFmpeg, MediaMTX. Khuyến nghị Python 3.12.
Cài PyTorch/torchvision cùng bản CUDA hoặc cùng bản CPU; không trộn hai loại.

```powershell
python -m pip install -e ".[inference,dev,benchmark]"
```

Môi trường riêng của phiên này ở `D:\MyWork\Tracking_Detection\.tools\bellevue-env`.
Các gói YOLO/torchvision riêng đã được chuyển từ ổ C sang
`D:\MyWork\Tracking_Detection\.tools\bellevue-inference`, không thay đổi Python hệ thống.
Nếu dùng môi trường này thì thêm đường dẫn đó vào `PYTHONPATH` của phiên PowerShell.
MediaMTX native ở `.tools/mediamtx-1.9.3`; FFmpeg ở `.tools/bellevue-video`.

## Chạy 4 nguồn RTSP đồng thời trên máy

Chạy từ thư mục gốc mã nguồn, truyền đường dẫn tuyệt đối tới hai chương trình:

```powershell
python -m scripts.run_realtime --mediamtx "D:\duong-dan\mediamtx.exe" `
  --ffmpeg "D:\duong-dan\ffmpeg.exe" --output data/realtime/run-01
```

Launcher chỉ bind `127.0.0.1`, dùng API cổng 18000 và RTSP cổng 18554 để tránh
đụng cấu hình đang chạy. Mỗi lần chạy chọn một thư mục kết quả mới.

- API: `http://127.0.0.1:18000/docs`.
- Nguồn: `rtsp://127.0.0.1:18554/source/cam01-eastgate` và ba ID còn lại.
- Đầu ra mở VLC:
  - `rtsp://127.0.0.1:18554/processed/bellevue/eastgate`
  - `rtsp://127.0.0.1:18554/processed/bellevue/newport`
  - `rtsp://127.0.0.1:18554/processed/bellevue/se38th`
  - `rtsp://127.0.0.1:18554/processed/bellevue/ne8th`

Ctrl+C ở launcher yêu cầu API và nguồn phát lại dừng mềm qua file tín hiệu của
chính lần chạy, đợi đóng thread/capture/publisher rồi dừng MediaMTX. `cleanup.json`
ghi exit code mềm và các tiến trình con còn sót. Không dừng tiến trình ngoài tác vụ.

## Đo benchmark

```powershell
python -m benchmarks.run --mediamtx "D:\duong-dan\mediamtx.exe" `
  --ffmpeg "D:\duong-dan\ffmpeg.exe" --seconds 60 --warmup 5 `
  --output data/benchmark/run-01
```

Mặc định chạy đủ 6 tổ hợp (1,4,8) × (serial,batch). Kết quả gồm:

- `benchmark.json`: cấu hình máy, số liệu từng tổ hợp và thời điểm đo.
- Mỗi tổ hợp: log API/replay/MediaMTX, log metrics, SQLite, snapshots,
  `measurement.json`, ảnh đồng thời khi có từ 4 nguồn, và `cleanup.json`.
- FPS detect đo từ số frame xử lý theo thời gian thực; FPS RTSP đo bằng client giải mã.
- `unique_source_fps` đếm timestamp nguồn khác nhau, không coi frame lặp là detect mới.
- CPU là tổng phần trăm của tiến trình đo và các tiến trình con (có thể hơn 100%);
  RAM RSS cộng các tiến trình có thể tính trùng trang chia sẻ, không phải VRAM.
- Thử tải 8 camera dùng bốn góc gốc nhân thành 8 luồng độc lập; không tuyên bố có
  tám vị trí camera khác nhau.

### Phạm vi phép đo độ trễ

Nguồn phát lại ghi đồng hồ millisecond vào dải pixel nhỏ. Marker có CRC; probe đọc
lại sau cả hai chặng encode/RTSP/decode. Đồng hồ nguồn và probe cùng máy.

Đây là **replay-source → decoded RTSP output**, có cả capture/encode nguồn, RTSP
đầu vào, detect/track, RTSP đầu ra và decode phía nhận. Không bao gồm thời điểm
phơi sáng của camera vật lý và **không bao gồm buffer/hiển thị của VLC**. Muốn kết
luận yêu cầu dưới 1 giây tới màn hình VLC, cần đo thêm hoặc quay màn hình đồng hồ.

`internal_latency_ms` là một chỉ số khác, ngắn hơn; không dùng thay số đo trên.
`meets_latency` chỉ đúng khi ít nhất 95% frame giải mã được marker và độ trễ lớn
nhất đo được dưới 1000 ms. Không lấy FPS lưu trong file MP4 để chứng minh realtime.

## Docker

```powershell
docker compose config --quiet
docker compose up --build
```

Compose hiện dùng image CPU; không tự dùng GPU Windows. Nếu muốn GPU trong Docker,
cần Docker Desktop/WSL2 và runtime NVIDIA phù hợp, rồi đo lại. Trong phiên này
Docker engine chưa chạy nên mới xác minh được cấu hình, **chưa build/chạy container**.

## Các kiểm tra bắt buộc trước khi nộp

1. Thay một nguồn bằng video có người sau khi tải xong; căn lại vạch/zone theo góc đó.
2. Chạy đủ benchmark, giữ cả kết quả không đạt và giải thích nguyên nhân.
3. Tắt một nguồn RTSP: nguồn khác vẫn chạy, reconnect count của nguồn lỗi tăng.
4. Dừng đúng PID FFmpeg publisher của một camera lấy từ API: publisher phải tự bật lại.
5. Bật/tắt camera qua API, lọc sự kiện theo camera/thời gian, kiểm tra ảnh snapshot.
6. Đứng trong zone không phát lại sự kiện mỗi frame. `first_seen_inside` ghi riêng,
   không gọi là lượt đi vào. Tracker đổi ID vẫn là giới hạn cần nêu trong báo cáo.
7. Ctrl+C: kiểm tra `cleanup.json`, không còn FFmpeg/thread của lần chạy.
8. Quay `Demo_HoTenKhongDau.mp4` từ lần service thật chạy đồng thời 4 camera.
9. Viết `BaoCao_HoTenKhongDau.pdf` gồm link GitHub, bảng benchmark và nhận xét.

## Trạng thái đo trên máy ngày 22/10/2026

Lần chạy thật ban đầu thất bại do Windows báo `WinError 1455` khi nạp
`torch_python.dll` (bộ nhớ phân trang không đủ), đồng thời chỉ còn khoảng 550 MB
RAM trống trên máy khoảng 8 GB RAM. Đã dừng và kiểm tra không còn tiến trình con
của lần thử đó. Chưa có số liệu đạt 4 × 10 FPS hoặc độ trễ dưới 1 giây.
Không tự đóng ứng dụng của người dùng hoặc thay đổi pagefile của Windows.

### Thử lại sau khi giải phóng ổ C

Ngày 22/10 đã chạy lại YOLO11n CUDA, kích thước inference 640 trên các nguồn
Bellevue 1280×720, RTX 3050 Laptop, RAM vật lý khoảng 8 GB. RAM khả dụng vẫn thấp;
lần thử chủ động dùng `--min-free-ram-mb 500` thay ngưỡng bảo vệ mặc định 1800 MB.
Đây chỉ là smoke test ngắn, không thay thế benchmark 60 giây và ma trận đầy đủ.

| Lần thử | Thời gian đo | FPS detect/camera | Kết luận |
| --- | --- | --- | --- |
| `data/benchmark-smoke-02`, 1 camera serial | 10 giây | 12,78 | Chạy được; độ trễ tối đa 3,07 giây, chưa đạt yêu cầu độ trễ |
| `data/benchmark-smoke-03`, 4 camera batch | 20 giây | 2,50–2,60 | Cả 4 xử lý được, chưa đạt 10 FPS/camera |
| `data/benchmark-smoke-04`, 4 camera batch, probe TCP | 20 giây | 2,55–2,70 | Còn timeout/lỗi giải mã đầu ra; chưa đạt FPS và độ trễ |

Trong lần cuối, median độ trễ từng đầu ra khoảng 0,94–2,23 giây, tối đa khoảng
2,02–3,62 giây. Probe vẫn có lỗi nên không dùng các mẫu này để tuyên bố đầu ra ổn
định. FPS giải mã có thể gồm frame lặp; FPS detect mới là số khung hình thực xử lý.
Chưa quy kết nút thắt hoàn toàn cho RAM hay GPU khi chưa có profiling riêng.

`measurement.json` giữ số đo từng camera; `simultaneous-preview.jpg` là ảnh ghép
khung hình gần nhất của bốn probe trong cùng phiên chạy, không phải video demo
hay bốn thời điểm phơi sáng đồng bộ. Cả ba lần có `cleanup.json` xác nhận service
và replay thoát bình thường, không còn tiến trình con do lần thử tạo ra.

Kiểm thử hồi quy: **48 passed, 1 skipped, 7 subtests passed**. Kiểm thử offline
dùng cặp lệnh `ffmpeg`/`ffprobe` trên PATH bị bỏ qua vì môi trường hiện chỉ có bản
FFmpeg nhúng; ba kiểm thử render batch dùng `FFMPEG_TEST_BIN` đã chạy. Ruff đã qua.
Docker mới xác minh cấu hình, chưa chạy container; benchmark đủ 1/4/8 × hai chiến
lược, nguồn có người, demo MP4 realtime và báo cáo PDF vẫn cần hoàn thành.
