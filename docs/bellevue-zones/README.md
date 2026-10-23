# Bản căn vùng Bellevue — chưa chạy detection

- `overview.jpg`: tổng quan bốn camera, tại giây 30.
- `cam*-zones.jpg`: ảnh đầy đủ 1280×720 của từng camera.
- `cam*-timeline.jpg`: đối chiếu vùng ở các mốc 0, 90 và 179 giây.
- Xanh: vùng đếm dự kiến chiếm khoảng 75% phần giao lộ đã chọn.
- Đỏ: zone cảnh báo thử nghiệm chiếm khoảng 25%, đặt ở phía phải trên ảnh.
- Hai vùng không chồng nhau, chỉ chung đường biên.

## Tọa độ và cách dựng lại

Chỉnh bốn đỉnh của phần giao lộ trong `configs/bellevue-region-layout.json`.
Thứ tự đỉnh: trên trái → trên phải → dưới phải → dưới trái.

Chạy từ thư mục gốc dự án:

```powershell
python -m scripts.preview_bellevue_regions
```

Tọa độ đa giác kết quả nằm trong `configs/bellevue-regions.json`.
Tỉ lệ được tính bằng diện tích pixel của đa giác, không phải diện tích thực trên mặt đường.
Đường phân chia được tìm để đạt tỉ lệ diện tích 75/25, không chia đơn giản theo chiều rộng.
Sai số nhỏ do tọa độ làm tròn về pixel nguyên.

## Phạm vi sử dụng

File tọa độ là tài liệu hình học, **không phải file AppConfig có thể đưa trực tiếp vào ứng dụng**.
Cấu hình chạy đã được nối tại `configs/bellevue.yaml`; bộ đếm đa giác ở
`app/events/region_counter.py`. Mỗi ID chỉ được đếm một lần khi quan sát thấy chuyển
từ ngoài vào vùng xanh. Xe xuất hiện lần đầu ngay trong vùng được ghi riêng, không
tính là lượt đi vào. ID bị mất rồi tạo lại có thể ảnh hưởng độ chính xác thống kê.
Các ảnh trong thư mục này vẫn là ảnh căn vùng, không phải kết quả detection.

Cấu hình không lọc detection theo đa giác giao lộ: cần theo dõi cả xe đang tiếp cận
để xác định lượt đi vào vùng xanh. Chỉ logic đếm giới hạn ở `counting_region`.
Zone đỏ vẫn kiểm tra tất cả track; `Zone alerts` gồm cả `entry` và `first_seen_inside`.

Zone đỏ là vùng do người dùng yêu cầu để thử nghiệm cảnh báo, không đại diện cho vùng
cấm giao thông thực tế. Camera SE38th có cột đèn che một phần mặt đường; bản căn vùng
không thể loại bỏ vật che khuất đó. Đã kiểm tra bằng mắt tại ba mốc, chưa kiểm tra liên tục
toàn bộ video hoặc hiệu chuẩn biến dạng ống kính.
