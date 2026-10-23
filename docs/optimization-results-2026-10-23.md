# Kết quả tối ưu 4 camera — 23/10/2026

## Kết luận

Video RTSP có ảnh nguồn mới tăng khoảng 2,35 lần trong hai lượt đo này. Bản tối ưu
đạt hơn 10 FPS đầu ra và hơn 10 timestamp nguồn mới/giây ở cả bốn camera;
độ trễ ảnh lớn nhất ghi nhận là 861 ms. **YOLO không tăng FPS**: detect thật còn
2,67–3,02 FPS/camera, thấp hơn baseline. Đây là đánh đổi ưu tiên video mới, không
phải kết quả đạt 10 lượt detect/giây/camera hoặc chứng minh đếm chính xác hơn.

## Điều kiện đo

- Ryzen 6 nhân/12 luồng, RTX 3050 Laptop 4 GB, driver 546.92; Windows, RAM lắp 8 GB.
- Cùng bốn file cam01-eastgate, cam02-newport, cam04-ne8th và cam05-crosswalk.
- YOLO11n, imgsz480, confidence 0,25, năm lớp person/car/motorcycle/bus/truck.
- Cả hai có nguồn replay 15 FPS, RTSP/TCP và bốn client FFmpeg giải mã độc lập.
- Mỗi lượt đo 60 giây sau khi có detection ở cả bốn camera và warmup client 8 giây.
- Baseline: `data/benchmark-optimization-baseline-02/benchmark.json`.
  Model FP32, worker chờ YOLO, IoU cũ, CPU libx264, mục tiêu output12.
- Tối ưu: `data/benchmark-optimized-03/benchmark.json`.
  FP16, render bất đồng bộ, Kalman/IoU dự đoán tối đa700ms, detect interval2,
  NVENC với FFmpeg tương thích, mục tiêu output14, batch tối đa4/chờ15ms.
- RAM khả dụng trước hai lượt tương ứng2305MiB và2470MiB; ngưỡng kiểm tra1500MiB.
  Không thay driver hay đóng thêm ứng dụng trong các lượt đo.
- Các file nguồn giống nhau nhưng đoạn bắt đầu đo không được khóa frame-for-frame;
  thời gian startup/warmup khác nhau. Đây là đối chứng vận hành, chưa phải phép
  thử chuẩn hóa cùng tập ảnh hoặc lặp nhiều lần có khoảng tin cậy.

## FPS ảnh nguồn mới và độ trễ đầu ra

| Camera | Nguồn mới/giây baseline | Nguồn mới/giây tối ưu | Max latency baseline | Max latency tối ưu |
|---|---:|---:|---:|---:|
| Eastgate | 4,97 | 11,38 | 945ms | 806ms |
| Newport | 4,92 | 11,38 | 1119ms | 861ms |
| NE8th | 4,87 | 11,53 | 1570ms | 783ms |
| Crosswalk | 4,65 | 11,21 | 1468ms | 846ms |

| Camera | YOLO FPS baseline | YOLO FPS tối ưu | FPS video giải mã tối ưu | P95 latency tối ưu |
|---|---:|---:|---:|---:|
| Eastgate | 4,97 | 2,90 | 12,01 | 666ms |
| Newport | 5,00 | 3,02 | 12,01 | 660ms |
| NE8th | 4,93 | 2,78 | 12,01 | 671ms |
| Crosswalk | 4,75 | 2,67 | 12,08 | 696ms |

Coverage timestamp nguồn và đầu ra đều100% trong lượt tối ưu. Latency chỉ là
replay capture → client giải mã trên cùng máy, **không** gồm phơi sáng camera thật
hay bộ đệm hiển thị VLC; cũng **không** phải tuổi bbox/event detect.

## Giới hạn cần giữ nguyên khi báo cáo

- Tuổi detection lớn nhất **trong các mẫu API** lần lượt1066/904/1062/1158ms.
  Không được lấy ảnh nền trễ dưới1giây để khẳng định mọi detection/event cũng dưới1giây.
- Bbox quá700ms bị ẩn và hiện nhãn `TRACK STALE`. Có134/112/177/183 frame như vậy
  trong cửa sổ đo, tương ứng khoảng17%/14%/23%/24% frame render. Không bỏ các frame
  này khỏi mẫu FPS, không giả vờ chúng có kết quả tracking mới.
- Sự kiện chỉ từ detection thật; dự đoán không tự tạo count/intrusion. Tuy vậy,
  bỏ lượt detect và ghép sai/mất ID vẫn có thể ảnh hưởng độ chính xác đếm.
  Chưa đo IDF1/MOTA/precision-recall và chưa đối chiếu số đếm với ground truth.
- Tổng CPU trung bình tăng579%→639% (tổng các tiến trình, có thể lớn hơn100%).
  Vì vậy không tuyên bố đã giảm toàn bộ tải CPU nhờ NVENC.
- Tổng RSS đỉnh các tiến trình giảm2000→1517MiB. Đây là tổng working set,
  có thể tính trùng trang dùng chung, không phải RAM vật lý riêng biệt tuyệt đối.
- Cả hai lượt có cleanup.json: service/replay thoát mềm, không còn descendant sở hữu.
- `benchmark-optimized-01` bị ngắt trước khi đo, không có benchmark hợp lệ.
  `benchmark-optimized-02` là thử20giây/output12; giữ riêng, không gộp vào lượt60giây.
- Chưa chạy lại ma trận8camera hay cập nhật PDF nộp bài cũ. Không kết luận đã đủ mọi
  tiêu chí chỉ từ việc bốn đầu ra RTSP đạt FPS/latency trong60giây.

## Chạy và kiểm tra lại

- Ruff: qua toàn bộ mã nguồn.
- Pytest: 87 test + 7 subtest, không lỗi/không skip;
  kết quả máy đọc được tại `data/verification/optimized-tests.xml`.
- Video minh họa riêng30giây: `output/optimized/TranDanhThien/Demo_ToiUu_4Camera.mp4`.
  Lấy mẫu bốn RTSP thực đồng thời,240 mẫu ở mục tiêu8FPS rồi encode VFR theo thời
  gian thực. Đây không phải video chứng minh FPS detect; benchmark60giây ở trên
  được chạy riêng, không kèm tải recorder.

Xem `docs/optimization-2026-10-22.md` và `configs/submission-optimized.yaml`.
Baseline và cấu hình mặc định cũ vẫn giữ nguyên để dùng khi ưu tiên detect/đếm
hơn số ảnh video mới. Bản tối ưu là lựa chọn riêng, không âm thầm thay default.
