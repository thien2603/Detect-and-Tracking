# Nguồn video cao tốc

Bài nguồn của VietNamNet:
https://vietnamnet.vn/tac-tren-cao-toc-ngay-le-nhieu-o-to-di-vao-lan-khan-cap-chen-duong-xe-cap-cuu-2276071.html

Theo bài báo: quay trên cao tốc Hải Phòng–Hạ Long, cầu Bạch Đằng ngày 28/4/2024,
và Hải Phòng–Hà Nội ngày 30/4/2024. Đây là video báo chí từ camera trong xe, có cắt cảnh,
không phải camera CCTV cố định và không phải dataset có giấy phép mở.

`scripts/download_expressway.py` đọc iframe công khai, chọn HLS 480p, tải các đoạn theo
thứ tự, kiểm tra FPS gốc 30000/1001, sửa khoảng hở timestamp, resize 640x360 và lấy mẫu
10 FPS. Không bỏ phần nội dung để tạo cảnh báo, không lặp để đủ thời lượng.
Lưu URL và SHA-256 trong `.source.json` cạnh video. Không tải nguồn cần đăng nhập,
không giải mã DRM. Nếu cấu trúc nguồn hoặc FPS đổi, script dừng để kiểm tra.

Trong các khung đại diện của phiên trước không thấy xe máy; không bảo đảm tuyệt đối
từng frame không có xe máy. Nguồn có xe khách, van và tải. `classes: [car]` chỉ lọc
kết quả nhận diện, không xóa các phương tiện khác khỏi hình.

Bốn video giao thông cũ không còn trong workspace và không nằm trong ZIP này.
Các trang nguồn đã dùng trước đây: https://videodatasets.org/UrbanMotorbike/mb7500.htm,
https://videodatasets.org/UrbanMotorbike/mb10000.htm và
https://homepages.inf.ed.ac.uk/thospeda/downloads.html. Không tự gán nhãn những video đó
là cao tốc Việt Nam. Cấu hình 4 camera hiện là mẫu nhận video bạn cung cấp.
