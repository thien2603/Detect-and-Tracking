# Kiểm tra bản dựng lại 0.2.0

Ngày kiểm tra: 20/10/2026. Linux, Python 3.12, CPU. Phiên bản thư viện trực tiếp
được ghi trong `requirements-tested.txt`. Đây là kết quả chạy mới, không tái sử dụng
benchmark hoặc kết quả kiểm thử từ phiên cũ.

## Kết quả

- `python -m pytest`: **28 passed**. Bao gồm IoU/class matching, miss/expiry,
  điểm trên biên đa giác, lọc ROI trước sự kiện, entry/re-entry/first_seen_inside,
  đường đếm hữu hạn và deadband, nội suy/tạm dừng lịch vùng, cấu hình, SQLite,
  hàng đợi inference, bật/tắt API, UUID phiên, snapshot và render H.264 bằng FFmpeg.
- `ruff check app scripts tests benchmarks`: passed.
- `compileall`: passed.
- Tải trọng số YOLO11n chính thức thành công. YOLO CPU thực hiện suy luận thành công;
  cấu hình `car` ánh xạ vào COCO ID 2.
- Tải lại video công khai bằng `scripts.download_expressway`: **125,8 giây**,
  640x360, 10 FPS. Provenance và hash được lưu cạnh video.
- Chạy đầy đủ renderer với YOLO thật: **1.258 frame**, H.264/yuv420p, 640x360,
  10 FPS, 125,8 giây. FFprobe xác nhận thông số; FFmpeg giải mã toàn bộ video không lỗi.
- Nhật ký có **33 cảnh báo**, gồm **9 entry** và **24 first_seen_inside**;
  tất cả thuộc lớp `car`. Ảnh của mọi sự kiện đều tồn tại. Đây không phải 33 xe
  vi phạm đã xác minh; thiếu nhãn chuẩn và tracker có thể đổi ID.
- Xuất/đọc RTSP thật bằng MediaMTX 1.9.3 native và FFmpeg/FFprobe: H.264,
  640x360. Sau kiểm tra, thread publisher/watchdog và tiến trình server được dừng.

## Phạm vi kiểm tra

Các test tự động sử dụng detector giả cho logic và API; các lần chạy YOLO/video
thật phía trên được thực hiện riêng. Chưa đo precision/recall, IDF1/MOTA, tốc độ
xe, nhận dạng biển số hay độ trễ đầu cuối. Chưa chạy trên Windows hoặc build Docker
trong phiên kiểm tra này. Script PowerShell và Docker Compose được cung cấp để
người dùng chạy trên máy đích; không khẳng định đã chạy thực tế trên Windows.

Cảnh báo DeprecationWarning từ tổ hợp Starlette/TestClient/httpx không làm thất bại test.
Không có kiểm tra hiệu năng 4/8 camera mới hoặc số liệu FPS bảo đảm cho máy khác.

ZIP chứa `MANIFEST.sha256.json` để kiểm tra SHA-256 từng file đóng gói và được kiểm
tra CRC sau khi tạo. Video/model/kết quả kèm theo là file của lần chạy mới.
