# Pipeline tối ưu: frame mới độc lập với lượt detect

> Đã chạy đối chứng 60 giây ngày 23/10/2026. Xem
> [kết quả và giới hạn thực tế](optimization-results-2026-10-23.md).

## Phạm vi thay đổi

- Giữ cấu hình và tracker IoU cũ để đối chứng; cấu hình mới là
  `configs/submission-optimized.yaml`. Không thay video, hình học zone hay vạch đếm.
- `model.async_inference: true`: mỗi camera có tối đa một yêu cầu YOLO chưa hoàn tất.
  Luồng vẽ lấy ảnh mới nhất, không chờ Future của YOLO. Không tạo queue frame dài.
- `model.detect_interval: 2`: không gửi detect liên tiếp trên mọi frame nguồn.
  Đây là khoảng cách tối thiểu giữa hai sequence, không đảm bảo một FPS detect cụ thể.
- `model.half: true`: yêu cầu FP16 khi dùng GPU CUDA; CPU/MPS vẫn dùng FP32.
- Warmup batch 1..4 chạy trên chính thread inference, trước khi bật camera/render.
  Dùng `rect: false` để giữ input 480×480 và giảm đổi shape; chờ gom batch 15 ms.
  Cấu hình tối ưu đặt mục tiêu phát 14 FPS, không phải cam kết đạt 14 FPS thực tế.
- Tracker Kalman 8D + ghép IoU theo class, có thời gian thực. Đây **không phải ByteTrack**.
  Khi vẽ, dự đoán không thay đổi state đo và hết hạn sau 700 ms. Chưa học vận tốc hoặc
  xe đổi hướng/che khuất mạnh vẫn có thể mất ID; chưa có đánh giá IDF1/MOTA.
- Chỉ detection thật cập nhật đếm/zone và sinh snapshot. Dự đoán chỉ dùng hiển thị,
  có nhãn `PRED ...ms`; không được dùng để tạo sự kiện đi vào vùng.
- Resize ảnh để vẽ RTSP ở tối đa 960×540, scale bản sao hình học/tracks/trails cho
  phần hiển thị. Detect, tracking, đếm và snapshot bằng chứng giữ hệ tọa độ nguồn.
- JPEG cho API chỉ encode khi gọi `frame.jpg`, có cache theo sequence.
- `streaming.encoder`: `libx264` (mặc định cũ), `h264_nvenc`, hoặc `auto`.
  Auto thử mã hóa thật một frame, cache theo binary, log lỗi, rơi về CPU nếu không
  hỗ trợ hoặc lỗi lúc chạy. Không coi danh sách `-encoders` là đủ chứng minh NVENC chạy.
- API có thời gian batch, thời gian round-trip YOLO, analytics, render và submit
  gần nhất. Đây là số đo từng lượt gần nhất, không phải profiler GPU chi tiết.

## NVENC trên máy hiện tại

Driver 546.92 không đáp ứng NVENC API 12.2 của FFmpeg 7.1 đang dùng.
Đã thử mã hóa NVENC thành công với binary FFmpeg 4.2.2 đi kèm wheel PyPI chính thức
`imageio-ffmpeg==0.4.9`, cài riêng trong `.tools/ffmpeg-nvenc-compat`.
Không thay driver, không thay binary 7.1, không thay package Python hệ thống.

Binary cũ này chỉ dùng thực nghiệm nguồn tin cậy trên loopback; không coi là giải
pháp triển khai lâu dài cho media không tin cậy. Khi triển khai cần chọn build FFmpeg
được duy trì và driver tương thích, rồi kiểm tra lại. Xem [hướng dẫn NVIDIA](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html).

`--ffmpeg` vẫn dùng cho nguồn replay và client đo. `--encode-ffmpeg` chỉ đổi binary
mã hóa đầu ra, nên probe vẫn dùng FFmpeg mới với các tham số hiện tại.

## Chạy lại

Từ thư mục gốc mã nguồn, trong PowerShell:

```powershell
$env:PYTHONPATH = 'D:\MyWork\Tracking_Detection\.tools\bellevue-inference'
$python = 'D:\MyWork\Tracking_Detection\.tools\bellevue-env\Scripts\python.exe'
$media = 'D:\MyWork\Tracking_Detection\.tools\mediamtx-1.9.3\mediamtx.exe'
$ffmpeg = 'D:\MyWork\Tracking_Detection\.tools\bellevue-video\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
$encode = 'D:\MyWork\Tracking_Detection\.tools\ffmpeg-nvenc-compat\imageio_ffmpeg\binaries\ffmpeg-win64-v4.2.2.exe'
& $python -m scripts.run_realtime --config configs/submission-efficient.yaml `
  --mediamtx $media --ffmpeg $ffmpeg --encode-ffmpeg $encode `
  --encoder auto --optimized --output data/realtime/optimized-01
```

Chọn thư mục output mới mỗi lần, không ghi đè kết quả cũ.
Để benchmark, thay `scripts.run_realtime` bằng `benchmarks.run` và thêm
`--counts 4 --strategies batch --seconds 60 --warmup 8`.
Baseline dùng cùng base config nhưng bỏ `--optimized`, `--encode-ffmpeg`, và đặt
`--encoder libx264`. Đo từng lượt, không chạy hai benchmark cùng lúc.

## Đọc kết quả đúng

- `detect_fps`: lượt YOLO hoàn tất/giây/camera.
- `render_fps`: ảnh nguồn mới được vẽ; có thể dùng vị trí dự đoán.
- `decoded_fps`: frame RTSP giải mã; có thể gồm ảnh lặp.
- `unique_source_fps`: số timestamp nguồn khác nhau tới client.
- Latency marker là replay capture → RTSP client decode, chưa gồm bộ đệm VLC.
- `sampled_detection_age_max_ms`: tuổi kết quả detect lớn nhất trong các mẫu API;
  đây là lấy mẫu, không phải cực đại tuyệt đối của mọi lượt YOLO.
- `stale_tracking_frames`: frame vẽ khi kết quả detect đã quá hạn dự đoán; lúc đó
  không vẽ bbox cũ. Không được lấy video nền mượt làm bằng chứng tracking luôn mới.

Không kết luận chất lượng đếm tốt hơn chỉ từ test chức năng hoặc FPS video.
Phép đo 60 giây đã có ở tài liệu kết quả, nhưng chưa chứng minh ổn định dài hạn,
10 lượt detect/giây/camera, chất lượng ID/đếm hay cấu hình 8 camera.
