# Tracking và vùng làn khẩn cấp

Chỉnh model, lớp nhận diện và nguồn trong `configs/vietnam-expressway.yaml`.
`classes: [car]` là ô tô con theo COCO, không bao gồm `bus`, `truck`, `motorcycle`.
Muốn theo dõi cả ô tô tải/khách có thể chọn `[car, truck, bus]`.

`configs/vietnam-expressway-zones.json` lưu các cảnh và keyframe đa giác trên ảnh
640x360. Tọa độ `[x, y]`, gốc ở góc trái trên, x sang phải và y xuống dưới.
Thứ tự đỉnh phải nhất quán qua các keyframe. Các đa giác phải không tự cắt; bộ kiểm tra
hiện kiểm tra số đỉnh/diện tích, chưa phát hiện mọi trường hợp tự cắt.

Các cảnh đã phục dựng từ cấu hình phiên trước:

- 4–35 giây: cầu Bạch Đằng, phần làn khẩn cấp bên phải vạch liền.
- 44–126 giây: cao tốc Hải Phòng–Hà Nội, phần làn khẩn cấp giữa vạch và hộ lan.
- Ngoài các khoảng trên: tạm dừng vùng để tránh áp tọa độ vào lúc camera đổi góc.

Nội suy tuyến tính giữa hai mốc. Khi đổi cảnh hoặc lặp file, xóa lịch sử tracker,
quy tắc và vệt di chuyển; không dùng lại ID cũ trong cùng phiên. Bản dựng lại dùng
`AnalyticsPipeline` cho cả renderer và API nên cả hai đều nạp được lịch vùng.

Điểm kiểm tra là tâm cạnh đáy bbox. Vùng đỏ thể hiện khu vực theo dõi; khung xe trong
vùng chuyển đỏ và footer hiện ID. Không có vùng cấm hợp pháp được xác nhận chỉ từ đa giác.
Làn khẩn cấp có thể được sử dụng hợp lệ trong tình huống khẩn cấp; có xe cấp cứu trong
nguồn. Mọi cảnh báo cần người xem lại, không phải kết luận vi phạm.

`intrusion` có metadata `reason`:

- `entry`: cùng ID được quan sát ở ngoài rồi trong vùng.
- `first_seen_inside`: lần đầu quan sát ID đã trong vùng.

Không phát lại cảnh báo ở mỗi frame khi xe vẫn ở trong. Ra rồi vào lại phát cảnh báo mới.
Đổi ID hoặc ranh giới nội suy lệch vẫn có thể gây thêm cảnh báo. Chưa có nhãn chuẩn để
đo độ chính xác. Số cảnh báo của bản dựng lại không được mặc định bằng số của bản cũ.

Xem thử vùng tại giây 60:

```powershell
.\.venv\Scripts\python.exe -m scripts.preview_regions --seconds 60
```

Nếu dùng video khác, tạo cấu hình/lịch vùng mới. Không dùng tọa độ này cho camera khác,
video crop/resize khác hoặc một phiên bản biên tập khác của bài báo.
