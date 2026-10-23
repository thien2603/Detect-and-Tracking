# Bổ sung sau đối chứng đề bài

Tác giả báo cáo: **Trần Danh Thiện**.
GitHub được người dùng cung cấp: https://github.com/thien2603/Detect-and-Tracking.git.
Các sửa đổi dưới đây nằm ở workspace local; chưa push GitHub hoặc upload Drive.

## Phần đã triển khai

- **F09:** schema chặn classes rỗng, tên trắng, ID âm, device sai cú pháp và URL
  RTSP sai; preflight kiểm tra weights/FFmpeg/schedule. Service load model,
  xác nhận classes và device trước khi mở API healthy hoặc tạo worker.
- Startup thất bại dọn logger/resource; có test đảm bảo chưa tạo worker/DB khi
  model không hợp lệ. Detector giả chỉ dùng trong test, không phải chế độ chạy nộp.
- Generator/replay/coordinator mặc định lấy **mọi camera trong YAML**, không
  âm thầm chỉ lấy bốn. `--count` chỉ dùng khi muốn chọn số nguồn/thử tải.
- **F01/F08:** integration test dùng MediaMTX và FFmpeg thật với bốn nguồn nhỏ:
  ngắt một nguồn, ba nguồn khác tiếp tục; bật lại và reconnect; kill đúng publisher
  do test sở hữu, PID mới và frame phục hồi; tắt/bật camera qua manager; dừng sạch.
  Detector trong test này là giả, nên không coi kết quả là benchmark YOLO.
- **F07:** khóa thao tác chống trùng event ID đến hết lưu snapshot/commit SQLite;
  test retry cùng ID đồng thời chỉ chèn một dòng. Không tuyên bố chống đếm trùng
  một xe thật khi tracker đổi ID; đây vẫn là giới hạn của IoU tracker.
- Đọc toàn bộ box YOLO về CPU một lần mỗi ảnh; giới hạn thread OpenCV và FFmpeg
  filter để giảm tình trạng nhiều thread cạnh tranh. Không dùng các thay đổi mã
  này làm bằng chứng tốc độ khi chưa đo.
- Toàn bộ `app`, `scripts`, `benchmarks` đã dùng logging thay cho `print`.
- Phiên coordinator tự kết thúc khi service con kết thúc hoặc có stop-file,
  tránh launcher tiếp tục chờ trong một số Windows terminal host.

## Nguồn có người và cấu hình nộp

File người dùng đã tải: `C:/Users/Admin/Downloads/video_002.avi` (609.227.532 byte,
1200×1100, 30 FPS, 5 phút). Giữ nguyên file gốc. `scripts/prepare_people.py` tạo
180 giây đầu dạng H.264, không resize/đổi tốc độ/loop. Bản MP4 đã được decode toàn
bộ: 5.399 frame, thời lượng xấp xỉ 180 giây; provenance nằm cạnh video.

`scripts/verify_people.py` dùng YOLO thật ở 7 thời điểm:
33 box person, 53 car, 6 bus, 5 truck. Đây là tổng detection qua các frame mẫu,
không phải số người/xe duy nhất hoặc đánh giá precision/recall.
Chi tiết và ảnh: `data/verification/people-detection.json`, `people-samples/`.

- `configs/people.yaml`: camera cam05-crosswalk và hình học minh họa riêng.
- `configs/submission-four.yaml`: cam01/cam02/cam04 Bellevue + Crosswalk, nguồn gốc
  và tọa độ phân tích được giữ nguyên; không ghi đè bộ Bellevue cũ.
- `configs/submission-efficient.yaml`: cùng nguồn, thử imgsz=480, đầu ra giới hạn
  960×540 và giữ tỷ lệ/làm tròn chẵn. Chỉ resize **sau annotate**, không thay hệ tọa độ
  detect/tracking/zone. Crop nguồn và vùng xanh/đỏ Bellevue không bị sửa.
- Vùng đỏ Crosswalk là demo, không chứng minh có quy định cấm đi bộ thật tại đó.

## Benchmark và tính đúng của phép đo

- `data/benchmark-submission-01`: sáu tổ hợp 1/4/8 × serial/batch, imgsz640,
  output kích thước gốc. Có nhãn dataset cũ và nhánh thay timestamp capture khi
  mất marker nguồn; giữ làm lịch sử, không dùng độ trễ để chứng minh đạt đầu-cuối.
- `data/benchmark-submission-02`: chạy lại đủ sáu tổ hợp, imgsz480/output nhỏ hơn,
  OpenCV 1 thread, marker nghiêm ngặt. Khi mất timestamp nguồn, **không** tự tạo
  marker từ timestamp capture. JSON có coverage marker nguồn và đầu ra.
- `data/benchmark-final-4cam`: thử serial/batch riêng sau khi thêm giới hạn
  `-filter_threads 1`; đây là revision khác, không trộn vào ma trận 02.
- `serial`: dùng chung model, batch=1; `batch`: model dùng chung, tối đa 4 frame,
  chờ gom 5 ms. Tám camera là tám luồng logic từ bốn clip, không phải tám vị trí.
- FPS output phải đo bằng client giải mã, tách khỏi FPS inference và frame lặp.
  Queue không dồn không tự chứng minh độ trễ dưới 1 giây.
- Độ trễ chỉ từ replay capture đến client decode cùng máy, chưa gồm VLC display
  buffer/phơi sáng camera thật. Chỉ đánh dấu đạt khi max <1000 ms và cả hai loại
  marker coverage ≥95%. Các lượt không có frame/marker không được tính là đạt.
- Mỗi lượt đo 20 giây sau warmup 8 giây, cần lặp lâu hơn để khẳng định ổn định.
  Giữ cả trường hợp không đạt; chưa coi việc có JSON là đã đạt 4 × 10 FPS.

## Demo và báo cáo

`scripts/record_demo.py` nhận **bốn RTSP đã xử lý** đang chạy đồng thời. Video có
thời gian biến thiên (VFR) theo timestamp lấy mẫu thực, không nén 60 giây chạy thành
30 giây video. Mục tiêu lấy mẫu mặc định 5 FPS, có thể lặp frame mới nhất và đánh
dấu STALE khi client không nhận frame lâu; không dùng FPS demo để chứng minh NFR.

`scripts/build_report.py` tạo báo cáo PDF đúng tên, lấy trực tiếp bảng benchmark,
JUnit, kiểm chứng person và các giới hạn. Dùng môi trường có `reportlab` (extra
`.[report]` hoặc Python bundled), font Arial có đủ dấu tiếng Việt. Không bịa số đo.

Bản ghi thử đầu bị chạy nhanh đã được giữ ở `data/verification/demo-first-attempt/`,
không dùng để nộp. Phiên demo đầu đã dừng service, nhưng phải dừng thêm hai launcher
rỗng; có `data/live-demo-01/cleanup-audit.json`. Không coi đó là Ctrl+C hoàn hảo;
coordinator đã được sửa và cần đối chứng ở phiên tiếp theo.

## Docker và các việc cần đóng

Compose hiện phát ba Bellevue + Crosswalk, tự sinh config runtime từ YAML readonly
vào `/tmp`; sửa thêm camera trong YAML không cần sửa code hoặc tham số `--count`.
`docker compose config --quiet` qua. Docker Desktop Linux engine không sẵn sàng,
nên chưa xác minh build/run; image CPU không đại diện hiệu năng native GPU.

Chưa được đánh dấu hoàn thành: hiệu năng bốn camera theo phép đo, chạy Docker,
webcam vật lý, VLC GUI, source local đã push GitHub, upload thư mục Drive đúng tên.
PDF/MP4 có đúng tên không có nghĩa tự động đạt tất cả tiêu chí. Không tự mở Docker
Desktop, đổi pagefile, đóng ứng dụng người dùng, push source hay chia sẻ video.

## Kết quả đóng phiên

- Kiểm thử cuối: **75 test chính và 7 subtest đạt**, không bỏ qua test nào;
  JUnit có 82 testcase; Ruff và Compose parse đã qua.
- Đã có đủ sáu tổ hợp trong ma trận 02 và hai lượt riêng 4 camera sau giới hạn
  FFmpeg filter. Lượt cuối batch: output **4,65–6,05 FPS/camera**, max latency
  **2.032,89 ms**; **chưa đạt** đồng thời 4 × 10 FPS và trễ dưới 1 giây.
- Demo cuối: `output/submission/TranDanhThien/Demo_TranDanhThien.mp4`, VFR theo
  thời gian thực, khoảng 30 giây, 150 mẫu từ bốn RTSP output. Toàn bộ video đã
  decode; **63 sự kiện** được lưu trong khoảng lấy mẫu, ảnh snapshot đủ.
  Bản cuối hiển thị bộ đếm hai chiều/entry/zone từ SQLite theo thời gian xử lý,
  nhãn `DB` để phân biệt với ground truth hoặc đồng bộ phơi sáng từng camera.
- Phiên live-demo-02 đã thử Ctrl+C; không còn process con và log có shutdown
  hoàn tất. Cờ raw `graceful_exit.service=false` do Uvicorn re-raise SIGINT sau
  khi đóng (không phải bỏ qua cleanup). Giữ nguyên dữ liệu gốc; runner đã thêm
  xử lý KeyboardInterrupt. Verifier đối chiếu log và process thay vì sửa cờ.
- `data/verification/submission.json` phân biệt rõ artifact kiểm tra qua với
  `all_assignment_criteria_passed=false`. Không coi có PDF/MP4 là đã đạt đề.
- Báo cáo có họ tên, link GitHub người dùng cung cấp, cấu hình máy, bảng số đo,
  nhận xét kiến trúc, F01–F10 và các phần chưa đạt. Nguồn sửa vẫn ở local.

## Lệnh tái kiểm tra

```powershell
# Điền đường dẫn FFmpeg/MediaMTX trên máy; test vẫn dùng localhost thật.
$env:FFMPEG_TEST_BIN = 'D:\MyWork\Tracking_Detection\.tools\bellevue-video\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
$env:MEDIAMTX_TEST_BIN = 'D:\MyWork\Tracking_Detection\.tools\mediamtx-1.9.3\mediamtx.exe'
python -m pytest -ra --junitxml=data/verification/all-tests.xml
python -m ruff check app scripts benchmarks tests
docker compose config --quiet
```

Trên môi trường hạn chế socket, cần cho phép loopback trước khi chạy TestClient/
RTSP tests; treo socketpair trong sandbox không tự chứng minh lỗi ứng dụng.
