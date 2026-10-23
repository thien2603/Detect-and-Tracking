"""Build the named PDF from measured artifacts; never invent missing benchmark results."""

import argparse
import json
import logging
from pathlib import Path
from xml.etree import ElementTree

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]


def read_json(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=ROOT / "data/benchmark-submission-02")
    parser.add_argument("--output", type=Path, default=ROOT
                        / "output/submission/TranDanhThien/BaoCao_TranDanhThien.pdf")
    parser.add_argument("--font-dir", type=Path, default=Path("C:/Windows/Fonts"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError("Report exists; use --overwrite only for your generated draft")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for name, file in (("Body", "arial.ttf"), ("BodyBold", "arialbd.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(args.font_dir / file)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyBold",
                                  italic="Body", boldItalic="BodyBold")
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "Body"
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 13
    styles["BodyText"].spaceAfter = 7
    styles["Heading1"].fontName = styles["Heading2"].fontName = "BodyBold"
    styles["Heading1"].fontSize = 17
    styles["Heading1"].leading = 22
    styles["Heading1"].textColor = colors.HexColor("#16324f")
    styles.add(ParagraphStyle("SmallCell", fontName="Body", fontSize=8, leading=11))
    styles.add(ParagraphStyle("ReportTitle", parent=styles["Heading1"], alignment=TA_CENTER,
                             fontSize=21, leading=27, spaceAfter=16))
    story = []

    def para(text, style="BodyText"):
        return Paragraph(str(text), styles[style])

    def add(text, style="BodyText"):
        story.append(para(text, style))

    def table(rows, widths):
        data = [[para(cell, "SmallCell") for cell in row] for row in rows]
        item = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        item.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf5")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ccd5df")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([item, Spacer(1, 9)])

    summary = read_json(args.benchmark / "benchmark.json", {})
    results = summary.get("results", [])
    people = read_json(ROOT / "data/verification/people-detection.json", {})
    demo = ROOT / "output/submission/TranDanhThien/Demo_TranDanhThien.mp4"
    add("HỆ THỐNG XỬ LÝ VIDEO<br/>ĐA CAMERA", "ReportTitle")
    add("Báo cáo bài tập thực tập - Trần Danh Thiện", "Heading2")
    add("Ngày lập: 22/10/2026. Hạn nộp theo đề: 23:59 ngày 23/10/2026.")
    add('Source GitHub do tác giả cung cấp: '
        '<link href="https://github.com/thien2603/Detect-and-Tracking">'
        'github.com/thien2603/Detect-and-Tracking</link>. '
        'Các sửa đổi trong phiên này nằm ở bản local; chưa xác nhận đã đẩy lên GitHub.')
    add("<b>Kết luận trung thực:</b> Có service bốn nguồn chạy đồng thời và các chức năng "
        "cốt lõi. Kết quả bên dưới không phải tuyên bố tất cả yêu cầu đã đạt. Các mục "
        "chưa đạt/chưa kiểm chứng được liệt kê riêng.")
    add("1. Thiết kế và dữ liệu", "Heading1")
    add("Mỗi camera có capture thread giữ frame mới nhất, worker tracking/sự kiện riêng, "
        "publisher FFmpeg và một URI RTSP đầu ra. Một scheduler công bằng dùng chung "
        "một YOLO11n: serial (batch=1) hoặc microbatch (tối đa 4 frame, chờ 5 ms). "
        "Writer SQLite/snapshot có queue giới hạn và metric lỗi/drop. FastAPI chạy "
        "độc lập để xem trạng thái, bật/tắt camera và tra cứu sự kiện.")
    add("Pipeline: capture → latest frame → YOLO → IoU tracking → line/polygon events "
        "→ annotate → FFmpeg → MediaMTX RTSP. Nhánh sự kiện → snapshot + SQLite + logging.")
    add("Cấu hình nộp: cam01-eastgate, cam02-newport, cam04-ne8th (Bellevue) và "
        "cam05-crosswalk (Bangkok, có người đi bộ). Các clip khoảng ba phút. "
        "Bốn YAML Bellevue gốc được giữ nguyên; vạch/zone Crosswalk là minh họa thủ công, "
        "không phải kết luận vi phạm giao thông. Chỉ số 75/25 là diện tích pixel.")
    add("Chọn thread cho I/O và một model dùng chung để tránh nhân bản trọng số/VRAM. "
        "FFmpeg và MediaMTX là tiến trình ngoài. IoU tracker đơn giản, có thể đổi ID khi "
        "che khuất hoặc chuyển động nhanh; không tuyên bố IDF1/MOTA hay đếm tuyệt đối.")
    story.append(PageBreak())
    add("2. Benchmark thực đo", "Heading1")
    machine = summary.get("machine", {})
    add(f"Máy: {machine.get('os', 'chưa ghi')}; Python {machine.get('python', '?')}; "
        f"CPU {machine.get('cpu', '?')}, {machine.get('physical_cores', '?')} nhân/"
        f"{machine.get('logical_cores', '?')} luồng; RAM "
        f"{machine.get('ram_bytes', 0) / 1024**3:.2f} GiB; GPU {machine.get('gpu', '?')}.")
    add("Mỗi tổ hợp đo khoảng 20 giây, sau khi các camera có ít nhất 5 frame xử lý và "
        "warmup thêm 8 giây; cùng model/imgsz=480/classes/device. Đầu ra giới hạn "
        "960×540, giữ tỷ lệ, không đổi tọa độ phân tích trên ảnh nguồn. Đây là benchmark ngắn, "
        "chưa có nhiều lần lặp. Tám camera là tám luồng logic nhân từ bốn video gốc. "
        "Một camera dùng view Bellevue đầu tiên. Không so 1-camera serial với 4-camera "
        "batch để kết luận về chiến lược. Danh tính nguồn đúng nằm trong "
        "configs/service.yaml từng lượt. OpenCV giới hạn 1 thread, PyTorch 2 thread.")
    rows = [["Nguồn / cách", "Detect FPS/cam", "Output FPS/cam", "Max trễ (ms)", "Đạt FPS / trễ"]]
    for count in (1, 4, 8):
        for strategy in ("serial", "batch"):
            result = next((r for r in results if r["camera_count"] == count
                           and r["strategy"] == strategy), None)
            cams = result.get("cameras", []) if result else []
            if not cams:
                rows.append([f"{count} / {strategy}", "Chưa có", "Chưa có", "-",
                             result.get("status", "Chưa chạy") if result else "Chưa chạy"])
                continue
            def span(key, items=cams):
                values = [c[key] for c in items if c.get(key) is not None]
                return f"{min(values):.2f}-{max(values):.2f}" if values else "Không có"
            delays = [c["latency_max_ms"] for c in cams if c.get("latency_max_ms") is not None]
            fps_ok = all(c.get("meets_10fps") for c in cams)
            lag_ok = all(c.get("meets_latency") for c in cams)
            rows.append([f"{count} / {strategy}", span("detect_fps"), span("decoded_fps"),
                         f"{max(delays):.0f}" if delays else "Không đo được",
                         f"{'Đạt' if fps_ok else 'Chưa'} / {'Đạt' if lag_ok else 'Chưa'}"])
    table(rows, [88, 95, 95, 86, 112])
    add("<b>Cách đọc:</b> đề yêu cầu ít nhất 10 FPS đầu ra mỗi camera, không bắt buộc "
        "10 FPS detect. Output FPS đo bằng client giải mã, không lấy con số cấu hình "
        "hay metadata MP4. JSON có thêm unique_source_fps để không coi frame lặp là "
        "detection mới. Không có marker/không có frame thì không đánh dấu đạt độ trễ.")
    add("Độ trễ: đồng hồ CRC ghi vào pixel ở replay capture, đọc lại sau RTSP đầu ra. "
        "Bao gồm hai chặng RTSP/codec và xử lý, nhưng chưa gồm buffer/hiển thị VLC "
        "hay phơi sáng camera vật lý. Không thay bằng internal_latency_ms. Điều kiện "
        "runner: max &lt;1000 ms, coverage marker nguồn và đầu ra đều ≥95%. Khi mất "
        "marker nguồn, bỏ marker đầu ra; không thay bằng đồng hồ capture.")
    add("Đối chứng lịch sử: data/benchmark-submission-01 có sáu lượt imgsz=640 và "
        "đầu ra kích thước gốc. Runner cũ tự điền timestamp capture khi mất marker "
        "nguồn; do đó độ trễ các lượt này chỉ tham khảo, không dùng chứng minh "
        "đạt đầu-cuối. Lượt 02 đo lại bằng phương pháp đã sửa. Thay cả độ phân giải "
        "và giới hạn thread nên không quy mọi cải thiện giữa 01/02 cho riêng batch.")
    comparable = {r["strategy"]: r for r in results if r["camera_count"] == 4 and r.get("cameras")}
    if len(comparable) == 2:
        averages = {s: sum(c["detect_fps"] for c in r["cameras"]) / 4
                    for s, r in comparable.items()}
        chosen = max(averages, key=averages.get)
        add(f"So tại 4 nguồn: detect trung bình serial={averages['serial']:.2f}, "
            f"batch={averages['batch']:.2f} FPS/camera. Cấu hình tốt hơn theo chỉ số này "
            f"trong lượt đo ngắn là <b>{chosen}</b>; không suy ra đã đạt output/trễ. "
            "Cần lặp phép đo trước khi chốt kiến trúc. Giữ model dùng chung để tiết "
            "kiệm VRAM; chọn batch_size theo các số đo, không theo cảm giác.")
    story.append(PageBreak())
    add("3. Đối chứng chức năng và kiểm thử", "Heading1")
    rows = [["Mã", "Kết quả và giới hạn"]]
    criteria = [
        ("F01", "File và RTSP đã chạy; test ngắt một RTSP trong 4 nguồn rồi phục hồi "
         "đã qua. Ba nguồn còn lại tiếp tục. Chưa thử webcam vật lý."),
        ("F02", "Single-slot capture, một pending request/camera, publisher queue=1; "
         "có test thay request chờ. Cần theo dõi buffer codec/network khi tải dài."),
        ("F03", "YOLO11n, classes/conf/imgsz từ YAML. Kiểm chứng người: "
         + (f"{people.get('class_counts', {})}; tổng box trong 7 frame mẫu, "
            "không phải số người duy nhất." if people else "chưa có artifact xác nhận.")),
        ("F04", "IoU class-aware, state riêng từng camera, test giữ ID/expiry/reset qua. "
         "Có thể đổi ID khi thiếu detection."),
        ("F05", "Line crossing hai chiều, deadband/cooldown, test đoạn hữu hạn. "
         "Không dùng lượt vào polygon thay đếm qua vạch."),
        ("F06", "Polygon entry, không lặp khi đứng trong, ra/vào lại phát event mới. "
         "First_seen_inside được phân biệt với entry."),
        ("F07", "SQLite có thời gian/camera/track/type/snapshot. Retry cùng event ID "
         "được khóa nguyên tử. Chưa bảo đảm một xe thật không trùng khi đổi track ID."),
        ("F08", "Có overlay và RTSP riêng; test kill đúng publisher rồi PID mới/frame "
         "phục hồi đã qua. Chưa xác minh VLC GUI mở đủ bốn nguồn."),
        ("F09", "Preflight weights/FFmpeg/schedule; URL/classes/device được kiểm tra; "
         "YOLO load/classes/device trước API healthy. Wrapper mặc định lấy mọi camera YAML."),
        ("F10", "FastAPI status/FPS, enable/disable, filter camera/time, snapshot/frame; "
         "test request sai và bật/tắt runtime đã qua."),
    ]
    rows.extend(criteria)
    table(rows, [40, 436])
    junit = ROOT / "data/verification/all-tests.xml"
    if junit.is_file():
        suite = ElementTree.parse(junit).getroot().find("testsuite")
        add("Pytest/JUnit (tính cả subtest): " + ", ".join(f"{k}={suite.get(k)}" for k in
                                         ("tests", "failures", "errors", "skipped")) + ".")
    else:
        add("JUnit cuối chưa được tạo; không tự ghi số test đạt.")
    add("Test RTSP dùng socket/codec/MediaMTX/FFmpeg thật nhưng detector giả và frame "
        "nhỏ để kiểm tra phục hồi, không phải chứng cứ tốc độ YOLO. Ruff kiểm tra "
        "mã; log ứng dụng ghi file, có metrics theo camera; helper đã chuyển sang logging.")
    story.append(PageBreak())
    add("4. Demo, vận hành và phần còn lại", "Heading1")
    final_four = read_json(ROOT / "data/benchmark-final-4cam/benchmark.json", {})
    final_batch = next((r for r in final_four.get("results", [])
                        if r.get("strategy") == "batch" and r.get("cameras")), None)
    if final_batch:
        cams = final_batch["cameras"]
        values = [c["decoded_fps"] for c in cams]
        delays = [c["latency_max_ms"] for c in cams if c.get("latency_max_ms") is not None]
        add(f"Thử riêng revision FFmpeg filter_threads=1: batch đạt output "
            f"{min(values):.2f}-{max(values):.2f} FPS/camera; max trễ "
            f"{max(delays):.0f} ms. Chưa đạt. Không trộn lượt này vào ma trận 02 "
            "vì khác revision; xem data/benchmark-final-4cam.")
    image = args.benchmark / "4cam-batch/simultaneous-preview.jpg"
    if image.is_file():
        story.append(KeepTogether([
            Image(str(image), width=476, height=267.75),
            para("Ảnh các frame gần nhất từ bốn RTSP probe trong cùng phiên. Không "
                 "khẳng định phơi sáng đồng bộ và không thay thế MP4 demo."),
        ]))
    add("Demo: " + ("đã có Demo_TranDanhThien.mp4, ghi client nhận bốn RTSP đầu ra thật. "
                     "VFR giữ thời gian lấy mẫu thật; bộ đếm DB hiển thị theo thời gian "
                     "xử lý để dễ đọc trên mosaic, không phải ground truth hay đồng bộ "
                     "phơi sáng. Frame có thể lặp, không dùng FPS video chứng minh hiệu năng."
                     if demo.is_file() else "chưa có MP4 demo được xác minh."))
    add("Dừng sạch: unit/integration shutdown qua. Phiên live-demo-02 đã nhấn Ctrl+C "
        "trong terminal, không còn process con; log xác nhận worker/scheduler và "
        "lifespan đã đóng. Uvicorn trả lại KeyboardInterrupt sau khi shutdown làm "
        "cờ exit-code-zero cũ ghi false; giữ nguyên cờ gốc, không đổi thành kết quả "
        "giả. Runner đã xử lý trường hợp này. Chi tiết: data/verification/submission.json.")
    add("Docker: có Dockerfile/Compose và cấu hình ba Bellevue + một Crosswalk. "
        "Compose parse được; Docker Desktop Linux engine chưa sẵn sàng tại lần kiểm "
        "tra. Chưa tuyên bố build/run container thành công. Image hiện dùng CPU, "
        "kết quả GPU native không đại diện tốc độ container CPU.")
    add("Cần đóng trước khi xác nhận đủ: hiệu năng bốn nguồn và trễ tới màn hình nếu "
        "chưa đạt; chạy Docker; kiểm chứng webcam/VLC; đẩy source local lên GitHub "
        "và kiểm tra link; upload đúng thư mục Google Drive TranDanhThien. Không "
        "tự công khai dữ liệu/source hoặc thay đổi pagefile/đóng ứng dụng của người dùng.")
    add("Artifact tái lập: configs/submission-four.yaml; benchmarks/run.py; "
        "data/benchmark-submission-01 và 02; data/verification; scripts/record_demo.py; "
        "docs/assignment-audit-2026-10-22.md. Các kết quả không đạt được giữ nguyên.")
    add("Nguồn và quyền sử dụng: Bellevue TrafficVideoDataset; Crosswalk Bangkok "
        "video_002.avi, Figshare article 29983897/file 57418396. Cần đối chiếu giấy "
        "phép Figshare với README của dataset trước khi phát hành lại video công khai.")

    def footer(canvas, doc):
        canvas.setFont("Body", 8)
        canvas.setFillColor(colors.HexColor("#526173"))
        canvas.drawString(20 * mm, 13 * mm, "Trần Danh Thiện | Bài tập thực tập đa camera")
        canvas.drawRightString(190 * mm, 13 * mm, str(doc.page))

    document = SimpleDocTemplate(str(args.output), pagesize=(210 * mm, 297 * mm),
                                 leftMargin=20 * mm, rightMargin=20 * mm,
                                 topMargin=17 * mm, bottomMargin=22 * mm,
                                 title="Bao cao he thong xu ly video da camera - Tran Danh Thien",
                                 author="Trần Danh Thiện")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    LOGGER.info("Built report: %s", args.output)


if __name__ == "__main__":
    main()
