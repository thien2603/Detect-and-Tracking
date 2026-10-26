# Báo cáo Trần Danh Thiện

`BaoCao_TranDanhThien.pdf`: bản ngắn 4 trang cập nhật ngày 26/10/2026.
`main.tex`: nguồn LaTeX, biên dịch bằng XeLaTeX hoặc Tectonic.

```powershell
tectonic main.tex
```

Hoặc `xelatex -interaction=nonstopmode -halt-on-error main.tex`.
Font ưu tiên Times New Roman và Consolas, có font dự phòng. Không cần ảnh phụ trợ.

Báo cáo gồm kiến trúc, thuật toán, cấu hình, F01–F10, benchmark 1/4/8 camera,
đối chứng số model và các mục chưa nghiệm thu. Hiệu năng lấy từ lượt 23/10;
test/lint và GitHub được kiểm tra lại ngày 26/10. Docker đã build/up và kiểm tra
bốn RTSP, API/event/snapshot, hot-toggle, shutdown ba container mã 0. Còn thiếu
latency toàn bộ 4 camera và nghiệm thu webcam/VLC/Drive; không tuyên bố đạt toàn bộ đề.

Demo 120 giây được giữ local tại
`output/final-submission/TranDanhThien/Demo_TranDanhThien.mp4` và không đưa lên Git.
Upload PDF/MP4 lên Drive vẫn là bước riêng chưa hoàn tất.
