# Đối chứng bài thực tập với kết quả thực tế

> Đây là bảng đối chứng **trước đợt sửa tiếp theo**. Xem
> [bản bổ sung và bằng chứng mới](supplement-2026-10-22.md) để biết phần đã sửa.

Ngày kiểm tra: 22/10/2026. Tài liệu gốc: `C:/Users/Admin/Downloads/TTS_Tuan1.pdf`, đủ hai trang.

## Kết luận

**Chưa đủ điều kiện xác nhận hoàn thành/nộp bài.** Service đã xử lý đồng thời bốn
nguồn Bellevue phát lại qua RTSP, có tracking, vạch, polygon, sự kiện và ảnh lưu.
Nhưng chưa chứng minh đạt hiệu năng, chưa có benchmark đầy đủ, Docker chưa chạy
thực tế, còn lỗ hổng kiểm tra cấu hình và thiếu bộ sản phẩm nộp đã xác minh.

Đánh giá dưới đây tách ba mức: đã có mã và kiểm thử; mới có một phần bằng chứng;
chưa đạt/chưa thực hiện. Unit test dùng detector giả không chứng minh tốc độ hay
độ chính xác YOLO thực tế. Không có phần trăm hoàn thành suy đoán.

## 1. Chức năng F01–F10

| Mã | Tiêu chí trong PDF | Đối chứng hiện tại | Đánh giá |
| --- | --- | --- | --- |
| F01 | RTSP/file/webcam, reconnect, lỗi một camera không dừng camera khác | `app/camera/capture.py` hỗ trợ ba loại; file và 4 RTSP đã chạy. Test giả lập lỗi mở RTSP rồi reconnect đã qua; chưa thử webcam thật và chưa ngắt/khôi phục một nguồn RTSP thật giữa phiên 4 camera. Test tắt một camera không thay thế thử mất kết nối. | Một phần; thiếu kiểm thử thực tế |
| F02 | Xử lý frame mới nhất, không dồn queue | Capture giữ một slot `latest`; scheduler chỉ một request chờ/camera; publisher queue tối đa 1. Test thay request đang chờ đã qua. Bộ đệm decoder/server vẫn cần đo riêng, không thể suy ra trễ dưới 1 giây từ queue Python. | Có thiết kế và kiểm thử cốt lõi; chưa stress dài |
| F03 | YOLO v8+, detect người và xe, class/conf/imgsz từ config | YOLO11n CUDA đã chạy xe; `app/inference/detector.py` truyền ba tham số từ YAML; Bellevue có `person`, car/motorcycle/bus/truck. Chưa có bằng chứng thử YOLO trên nguồn có người đi bộ được chọn. | Một phần bằng chứng |
| F04 | Tracking | `app/inference/tracker.py` IoU theo từng camera; unit test giữ ID sau bỏ sót ngắn, không ghép khác class, hết hạn/reset; ảnh chạy thật có ID. Đổi ID khi di chuyển nhanh/che khuất vẫn là giới hạn. | Đạt chức năng cơ bản; không tuyên bố độ chính xác tracking |
| F05 | Đếm qua vạch, tách hai chiều | `app/events/line_counter.py`, YAML có vạch, HUD A>B/B>A; test deadband, đoạn hữu hạn, cooldown đã qua; DB realtime có `line_crossing`. Vùng xanh đếm vào polygon không thay thế tiêu chí này. | Có mã, test và sự kiện thực tế |
| F06 | Đối tượng đi vào polygon cấm | `app/events/intrusion.py`; test ngoài→trong, đứng trong không lặp, ra→vào lại đã qua; DB realtime có intrusion. `first_seen_inside` được ghi riêng, không gọi là entry. | Có mã, test và sự kiện thực tế |
| F07 | Một sự kiện/lần vi phạm, đủ timestamp/camera/track/type/snapshot, SQLite | `app/events/types.py`, `repository.py`; test đứng yên không phát lại, retry cùng event ID không chèn trùng đã qua. DB lần cuối: 58 sự kiện, đủ trường bắt buộc, không thiếu snapshot. Đây là chống lặp theo track/event ID, chưa đảm bảo một xe vật lý không bị đếm lại nếu tracker đổi ID; writer có thể drop khi đầy và có metric báo. | Đạt kiểm thử theo ID; cần nêu giới hạn và thử tải |
| F08 | Vẽ box/ID/vạch/zone/count; RTSP riêng mở VLC; FFmpeg chết tự bật lại | `app/streaming/annotator.py`, `publisher.py`; ảnh ghép và bốn đường output có thật. Publisher có restart/watchdog nhưng chưa chủ động làm chết publisher rồi xác minh phục hồi; chưa xác minh mở đủ bốn luồng trong VLC, probe còn lỗi. | Một phần; chưa nghiệm thu đầy đủ |
| F09 | YAML toàn bộ; config sai báo ngay khởi động; thêm camera chỉ sửa config | Pydantic/loader kiểm tra nhiều lỗi; trùng ID, RTSP input sai, file nguồn thiếu đã có test. Tuy nhiên model lazy-load trong worker: classes rỗng/sai, weights thiếu không được kiểm tra đầy đủ lúc startup; FFmpeg executable và RTSP output URL cũng thiếu preflight. Core manager duyệt YAML động, nhưng wrapper replay/runtime mặc định lấy đúng 4 camera, có thể bỏ camera thứ 5. | Chưa đầy đủ; có thiếu sót trong mã |
| F10 | FastAPI: status/FPS, bật/tắt runtime, lọc event camera/thời gian | `app/main.py`; TestClient qua các trường hợp bật/tắt, ID không tồn tại, request sai, snapshot/frame, time invalid. Repository test lọc camera/time qua. Status realtime có FPS, reconnect và publisher PID. Chưa test mọi thao tác này với bốn luồng YOLO thật cùng lúc. | API/test cốt lõi đạt; còn kiểm thử tích hợp |

## 2. Phi chức năng

| Tiêu chí trong PDF | Bằng chứng | Đánh giá |
| --- | --- | --- |
| Bốn nguồn chạy đồng thời theo pipeline capture→detect/track→event→draw→FFmpeg→RTSP | [Ảnh cùng phiên 4 camera](../data/benchmark-smoke-04/4cam-batch/simultaneous-preview.jpg), DB và log từng camera | Đã chạy được pipeline, chưa đồng nghĩa đạt tốc độ/ổn định |
| Mỗi camera ít nhất 10 FPS đầu ra, trễ đầu-cuối dưới 1 giây | Bảng số đo bên dưới; ba probe dưới 10 FPS, mọi max latency trên 1 giây; còn lỗi giải mã | Chưa chứng minh đạt |
| Ghi rõ máy test | `benchmark.json`: Windows, Python 3.10.11, CPU 6 nhân/12 luồng, RAM 7.722.795.008 byte, RTX 3050 Laptop 4 GB, driver 546.92 | Đã có metadata máy |
| Ctrl+C dừng sạch thread/process/FFmpeg/capture | Test manager shutdown qua; ba lần chạy có cleanup không còn descendant, service/replay thoát mã 0. Benchmark dừng bằng stop-file/finally, chưa thử Ctrl+C từ terminal tương tác trong phiên audit. | Có bằng chứng cleanup; thiếu thử Ctrl+C trực tiếp |
| Logging ra file, không print; FPS/trễ/reconnect từng camera | `app` không có print; `service.log` có `camera_metrics`. Một số tiện ích tải/preview/package còn print, cần thay nếu tiêu chí áp dụng cho toàn repo. | Service đạt; tiện ích cần rà theo phạm vi chấm |
| Unit test đếm vạch và vùng cấm | `tests/test_rules.py`, vừa chạy lại toàn bộ suite | Đạt ở phạm vi test hiện có |
| Sử dụng Docker | Có Dockerfile/Compose; `docker compose config --quiet` thành công. `docker version` không tìm thấy pipe Docker Desktop Linux engine. Chưa build/run/container cleanup hay đo trong container. | Chưa xác minh chạy Docker |

### Đúng cách hiểu tiêu chí FPS

PDF yêu cầu **10 FPS đầu ra**, không ghi bắt buộc 10 FPS inference. Vì vậy không
được dùng riêng FPS detect thấp để kết luận trượt. Ngược lại, khai báo
`output_fps: 12` không chứng minh client nhận 12 FPS, và frame lặp không phải
detection mới. Cần báo riêng cả ba số: detect FPS, decoded output FPS và unique
source FPS. Câu trước đây coi 10 FPS detect là yêu cầu trực tiếp của PDF là chưa
chính xác; bảng này dùng đúng tiêu chí đầu ra.

### Lần đo gần nhất: bốn camera batch

Nguồn: [measurement.json](../data/benchmark-smoke-04/4cam-batch/measurement.json).
Đo khoảng 20,016 giây sau warmup, inference imgsz 640, nguồn 1280×720, batch tối đa
4 dùng chung model, chờ gom batch tối đa 5 ms.

| Camera | Detect FPS | Giải mã đầu ra FPS | Unique source FPS | Trễ p50 (ms) | Trễ max (ms) | Lỗi đọc probe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cam01-eastgate | 2,60 | 10,39 | 2,60 | 937,85 | 2022,66 | 0 |
| cam02-newport | 2,60 | 3,30 | 0,85 | 2233,07 | 3523,06 | 4 |
| cam03-se38th | 2,70 | 9,54 | 2,55 | 1015,45 | 3578,55 | 0 |
| cam04-ne8th | 2,55 | 7,79 | 1,90 | 1302,91 | 3619,64 | 1 |

Đây là quan sát client trong một smoke test, có timeout/lỗi giải mã nên không
khẳng định tốc độ xuất thực luôn bằng số probe nhận. Tuy vậy hoàn toàn chưa đủ
bằng chứng đạt tiêu chí. Trễ đo từ file replay capture đến frame RTSP đã decode
cùng máy, chưa bao gồm VLC display buffer hoặc phơi sáng camera vật lý. Không
dùng `internal_latency_ms` thay thế độ trễ này. Không quy kết nguyên nhân hoàn
toàn cho RAM/GPU khi chưa profile riêng.

Lần một camera serial đo 10 giây đạt detect khoảng 12,78 FPS nhưng max latency
3,07 giây; không dùng kết quả một camera chứng minh bốn camera đạt.

## 3. Benchmark bắt buộc

| Số camera | Serial: batch=1 | Microbatch: batch tối đa 4 |
| --- | --- | --- |
| 1 | Có smoke test 10 giây (`benchmark-smoke-02`) | Chưa đo |
| 4 | Chưa đo | Có hai smoke test 20 giây (`benchmark-smoke-03`, `04`) |
| 8 | Chưa đo | Chưa đo |

Có mã chạy ma trận trong `benchmarks/run.py` không có nghĩa đã đo đủ. Hiện chỉ có
hai tổ hợp khác nhau, không thể lấy 1-camera serial so với 4-camera batch rồi kết
luận batch tốt/kém do số camera khác nhau. Cần đo hai chiến lược tại cùng từng
mức 1/4/8, cùng video/model/imgsz/device/thời lượng và trạng thái tài nguyên, sau
đó giải thích lựa chọn bằng số liệu. PDF cho ví dụ chứ không bắt buộc phải dùng
multiprocessing; serial shared model và microbatch là hai cấu hình cần mô tả rõ.
Nên đo lâu hơn smoke test (ví dụ 60 giây và lặp lại); PDF không ấn định số giây.

Nếu 8 nguồn được nhân từ bốn video, phải khai báo là tám luồng logic độc lập từ
bốn góc gốc, không tuyên bố tám camera/vị trí độc lập. Chưa có số đo 8 nguồn.

## 4. Bộ sản phẩm nộp

Đã tìm theo mẫu tên trong workspace; chưa thấy bộ sau:

1. `BaoCao_HoTenKhongDau.pdf`: phải chứa link GitHub thật, bảng benchmark và nhận xét.
2. `Demo_HoTenKhongDau.mp4`: bốn camera service chạy cùng lúc, có sự kiện.
3. Thư mục Google Drive theo họ tên viết liền không dấu và hai file bên trong;
   chưa kiểm tra/tạo/upload. Không tự công khai source hay video.

Bốn MP4 render offline riêng lẻ không thay thế video demo service đồng thời;
ảnh ghép từ probe cũng không thay thế MP4 demo. README và tài liệu Markdown chưa
thay thế báo cáo PDF đúng tên. Chưa xác minh link GitHub truy cập được.

Hạn trong PDF: **23:59 ngày 23/10/2026**.

Nguồn có người đi bộ giúp chứng minh F03, nhưng PDF không bắt buộc một camera
thứ năm hoặc một dataset cụ thể. Có thể thay một trong bốn nguồn, căn vạch/zone
theo góc mới rồi kiểm tra người và xe. Vùng xanh 75%/đỏ 25% là yêu cầu thêm của
người dùng, không phải tỷ lệ được quy định trong PDF.

## 5. Kiểm tra đã chạy lại trong lần audit

- Đọc text và xem ảnh render đủ hai trang PDF bằng Poppler.
- Pytest: **48 passed, 1 skipped, 7 subtests passed**, 2,59 giây; dùng
  `FFMPEG_TEST_BIN` và cho phép socket loopback cho TestClient. Một test offline
  yêu cầu `ffmpeg`/`ffprobe` trên PATH bị skip, không tính là đã qua.
- Ruff: `All checks passed!`.
- Docker Compose parse qua; Docker engine không sẵn sàng. Không khởi động Docker.
- Kiểm tra SQLite bằng kết nối read-only: 58 sự kiện; 0 thiếu trường bắt buộc,
  0 thiếu ảnh snapshot. Việc này không chứng minh không đếm trùng một xe thật.
- Dry-run schema xác nhận classes rỗng, weights không tồn tại, FFmpeg không tồn
  tại và output RTSP URL sai vẫn được chấp nhận ở lớp cấu hình. Kiểm tra file
  nguồn có sẵn không bù được thiếu sót này. Không thay đổi YAML vận hành.
- Rà soát log/measurement/cleanup của các lần chạy đã hoàn tất; không chạy thêm
  benchmark YOLO nặng trong lần audit này và không thay đổi mã vận hành.

## 6. Những việc phải đóng trước khi xác nhận đủ

1. Hoàn thiện preflight config: weights/classes/device/FFmpeg/URL output; lỗi
   phải rõ ngay khi startup. Loại bỏ giới hạn mặc định bốn camera ở wrapper nếu
   muốn quy trình thêm camera thực sự chỉ sửa YAML.
2. Test tích hợp: mất/khôi phục một RTSP trong khi ba nguồn khác vẫn xử lý;
   kill đúng publisher do service sở hữu rồi xác nhận PID mới và frame ra trở
   lại; mở bốn luồng VLC; Ctrl+C thật; webcam thật nếu có thiết bị.
3. Xử lý timeout/decoder và profile hiệu năng, đo lại đầu ra bốn camera và độ
   trễ đúng phạm vi; không che kết quả chưa đạt bằng frame lặp/metadata FPS.
4. Hoàn thành sáu tổ hợp benchmark, ghi hardware, tài nguyên và phân tích lựa
   chọn kiến trúc; giữ cả kết quả không đạt.
5. Build/run Docker và kiểm tra luồng/sự kiện/shutdown trong container.
6. Kiểm chứng person trên video có người, quay demo bốn camera đồng thời, tạo
   báo cáo PDF có GitHub và số liệu thật; đặt tên/thư mục đúng và kiểm tra lại.

Đây là báo cáo kiểm tra, không phải xác nhận đã sửa hay hoàn tất các mục còn thiếu.
