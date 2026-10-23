# Đối chứng 4 camera / 4 model riêng

## Kết quả đã đo (60 giây/phương án)

| Phương án | Detect FPS trung bình/camera | Tổng detect FPS | CPU trung bình (tổng tiến trình) | GPU VRAM peak trong mẫu | Tổng RSS peak |
|---|---:|---:|---:|---:|---:|
| Model chung / microbatch | 5,01 | 20,04 | 576% | 380MiB | 1937MiB |
| 4 model riêng | 4,82 | 19,28 | 675% | 540MiB | 1991MiB |
| 4 model / CUDA stream riêng | 4,94 | 19,75 | 676% | 602MiB | 2008MiB |

| Camera | Model chung | 4 model | 4 model + stream |
|---|---:|---:|---:|
| Eastgate | 5,12 | 5,30 | 5,40 |
| Newport | 5,08 | 4,98 | 5,07 |
| NE8th | 5,00 | 4,57 | 4,58 |
| Crosswalk | 4,85 | 4,43 | 4,70 |

Đây là FPS YOLO hoàn tất, không phải FPS encode/lặp ảnh hay dự đoán. Không có
OOM hay resource guard bị kích hoạt ở ba lượt. RAM khả dụng nhỏ nhất trong mẫu
runtime tương ứng698/725/664MiB; không thể suy ra máy hoàn toàn không chịu áp lực
RAM chỉ từ việc chưa có OOM. Các con số VRAM là snapshot toàn GPU trong cửa sổ đo,
không phải peak tuyệt đối hoặc lượng dành riêng cho model.

Kết luận: **chưa có cải thiện tổng thể đáng kể khi đổi sang4model ở backend này**.
Chênh lệch trung bình khoảng-3,8% và-1,5% so với model chung; mới một lượt/phương án,
chưa đủ kết luận thống kê về chênh lệch nhỏ. CPU tăng khoảng17%; một camera nhanh
hơn nhẹ nhưng không đồng đều. Không đổi mặc định ứng dụng sang4model.

Max latency ảnh replay→client của camera chậm nhất lần lượt1497/1728/1729ms;
không phương án nào ở đây chứng minh mọi đầu ra đều dưới1giây. Coverage marker
nguồn/đầu ra đều100%. Không gộp với lượt preset async/FP16/NVENC ở tài liệu tối ưu:
đó là phép thử khác có đánh đổi FPS detect lấy FPS ảnh mới.

Cả ba cleanup.json xác nhận service/replay thoát mềm và không còn descendant của
lượt chạy. Đây là4model trong1process trên1GPU, không phải4GPU và không phải bản
ONNX của báo cáo người khác. Không lấy số này để kết luận mọi cách triển khai
4model đều không hiệu quả.

## Cách triển khai

Kiểm tra sau triển khai: Ruff qua; 94 test và7 subtest qua, không lỗi/không skip
(`data/verification/independent-tests.xml`). Có kiểm tra bốn detector thực sự khác
nhau, vào inference đồng thời, CUDA stream context, startup lỗi, hot-disable/enable
và ngắt/kết nối lại nguồn RTSP. Clone factory không giữ model gốc đã tắt trong RAM.
Sau dừng toàn bộ thử nghiệm, không còn FFmpeg/MediaMTX; RAM khả dụng khoảng2170MiB
tại lần kiểm tra cuối. Không sửa driver hoặc tự đóng thêm ứng dụng của người dùng.

- Mặc định vẫn là `model.instances: shared`, dùng chung model và scheduler.
- `model.instances: per_camera`: mỗi camera có một YOLODetector, một predictor,
  một scheduler/thread độc lập. Tất cả cùng process Python để dùng chung thư viện,
  không phải bốn process tải bốn bản thư viện PyTorch.
- Camera tắt sẽ dừng worker/scheduler riêng; bật lại tạo model cho camera đó.
  Lỗi startup model sau phải đóng các scheduler đã tạo trước, không để thread sót.
- Model được load/warmup tuần tự trước khi bật capture/render; đo FPS không gồm
  thời gian startup này. Startup bản nhiều model có thể lâu hơn và phải tính riêng
  khi đánh giá triển khai thực tế.
- `model.cuda_streams: true` tạo CUDA stream riêng cho mỗi detector khi dùng CUDA.
  Cả predict và chuyển kết quả về CPU nằm trong stream context; stream chờ phần
  khởi tạo weights ở stream ban đầu. Không sửa hoặc monkey-patch thư viện cài sẵn.

## Ba phương án đo

1. `batch`: một model, batch tối đa4/chờ5ms.
2. `independent`: bốn model, mỗi lượt batch1, không chờ gom, stream mặc định.
3. `independent_streams`: bốn model/bốn stream CUDA riêng, batch1.

Cả ba dùng cùng bốn video của submission-efficient, YOLO11n FP32, confidence0,25,
năm lớp và ảnh model cố định480×480 (`rect: false`), một lượt detect cho mỗi ảnh
được worker xử lý. Không bật async-render, Kalman hay bỏ lượt detect của preset
optimized. Cả ba mã hóa output bằng CPU libx264, output mục tiêu12FPS, cùng replay
15FPS và cùng bốn client FFmpeg. Không so trực tiếp với số24FPS của báo cáo người khác.

Đo60giây mỗi phương án, warmup client8giây, chạy tuần tự. Đo snapshot GPU2giây/lần
(có thêm thời gian gọi nvidia-smi, giống nhau ở cả ba lượt). GPU VRAM là số toànGPU,
bao gồm display/ứng dụng khác, không phải riêng weights; không thu được peak tức
thời giữa các mẫu hay trong toàn bộ startup. RAM là tổng RSS có thể tính trùng trang
dùng chung. Ngưỡng RAM trước mỗi lượt1500MiB; dừng nếu RAM khả dụng dưới256MiB hoặc
VRAM trống dưới256MiB trong mẫu runtime. Lỗi/không đạt được giữ nguyên, không bỏ mẫu.

Các video giống nhau nhưng không khóa đoạn bắt đầu đo theo cùng frame nguồn;
startup/warmup khác nhau. Đây là đối chứng vận hành, không phải cùng ảnh tuyệt đối
hoặc benchmark lặp nhiều lần có khoảng tin cậy. Mục tiêu là đo FPS detect thật,
không tăng FPS bằng lặp ảnh hoặc dự đoán.

## Giới hạn CUDA stream và backend

[PyTorch](https://docs.pytorch.org/docs/stable/notes/cuda) cho phép các stream khác
nhau thực thi đồng thời khi không có đồng bộ hóa chặn. Tuy nhiên, backend Ultralytics
đang cài có `Profile.time()` gọi synchronize toàn thiết bị tại ranh giới đo bước
preprocess/inference/postprocess. Vì vậy stream riêng **không đảm bảo** các model
chồng lấp GPU hoàn toàn; số thời gian từng bước cũng có thể gồm chờ model khác.
Không kết luận mọi kiến trúc4model (ví dụ ONNX Runtime hoặc bốn process) đều có cùng
kết quả với triển khai PyTorch/Ultralytics cùng process trong thí nghiệm này.

## Chạy lại

Dùng các đường dẫn công cụ như tài liệu optimization, chạy từ gốc mã nguồn:

```powershell
python -m benchmarks.run --config configs/submission-efficient.yaml `
  --mediamtx PATH_TO_MEDIAMTX --ffmpeg PATH_TO_FFMPEG `
  --encoder libx264 --square-input --sample-gpu --counts 4 `
  --strategies batch independent independent_streams --seconds 60 --warmup 8 `
  --min-free-ram-mb 1500 --output data/benchmark-model-modes-NEW
```

Để chạy realtime một phương án, dùng `scripts.run_realtime --model-mode per_camera`
và thêm `--cuda-streams` nếu cần. Không đồng thời bật `--optimized` nếu muốn giữ đúng
phép so sánh FP32/không bỏ detect của tài liệu này.

Kết quả thô: `data/benchmark-model-modes-01/benchmark.json` và thư mục theo strategy.
Lượt thử20giây ban đầu ở `data/benchmark-independent-smoke-01` chỉ kiểm tra chạy được,
không gộp vào các số đo60giây.
