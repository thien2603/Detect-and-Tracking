from dataclasses import replace

import cv2
import numpy as np

from app.events.geometry import point_in_polygon


def annotate_frame(
    frame,
    camera,
    tracks,
    counts,
    detect_fps,
    trails=None,
    alert_count=0,
    video_seconds=None,
    paused=False,
    output_size=None,
    prediction_age_ms=None,
    prediction_stale=False,
):
    if output_size:
        height, width = frame.shape[:2]
        max_width, max_height = output_size
        ratio = min(1, (max_width or width) / width, (max_height or height) / height)
        if ratio < 1:
            out_width = max(2, int(width * ratio) // 2 * 2)
            out_height = max(2, int(height * ratio) // 2 * 2)
            sx, sy = out_width / width, out_height / height

            def point(value):
                return round(value[0] * sx), round(value[1] * sy)

            def zone(value):
                return value.model_copy(update={"points": [point(p) for p in value.points]})

            camera = camera.model_copy(update={
                "counting_region": zone(camera.counting_region) if camera.counting_region else None,
                "forbidden_zones": [zone(z) for z in camera.forbidden_zones],
                "line": camera.line.model_copy(update={"start": point(camera.line.start),
                                                       "end": point(camera.line.end)})
                if camera.line else None,
            })
            tracks = [replace(t, bbox=(t.bbox[0] * sx, t.bbox[1] * sy,
                                       t.bbox[2] * sx, t.bbox[3] * sy)) for t in tracks]
            trails = {key: [point(p) for p in trail] for key, trail in (trails or {}).items()}
            frame = cv2.resize(frame, (out_width, out_height), interpolation=cv2.INTER_AREA)
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    if camera.counting_region:
        polygon = np.array(camera.counting_region.points, np.int32)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [polygon], (60, 215, 60))
        cv2.addWeighted(overlay, 0.10, canvas, 0.90, 0, canvas)
        cv2.polylines(canvas, [polygon], True, (60, 215, 60), 2, cv2.LINE_AA)
    for zone in camera.forbidden_zones:
        polygon = np.array(zone.points, np.int32)
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [polygon], (0, 0, 255))
        cv2.addWeighted(overlay, 0.12, canvas, 0.88, 0, canvas)
        cv2.polylines(canvas, [polygon], True, (0, 0, 255), 1, cv2.LINE_AA)
    active = []
    for track in tracks:
        inside = any(point_in_polygon(track.anchor, z.points) for z in camera.forbidden_zones)
        if inside:
            active.append(track.track_id)
        color = (0, 0, 255) if inside else (70, 220, 70)
        x1, y1, x2, y2 = (round(x) for x in track.bbox)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 1)
        if x2 - x1 >= 26 and y2 - y1 >= 20:
            label = f"{track.class_name.upper()} #{track.track_id}"
            label_x = min(max(0, x1), max(0, width - len(label) * 8))
            cv2.putText(
                canvas,
                label,
                (label_x, max(45, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                color,
                1,
                cv2.LINE_AA,
            )
        if trails and len(trails.get(track.track_id, [])) > 1:
            cv2.polylines(
                canvas,
                [np.array(trails[track.track_id], np.int32)],
                False,
                (255, 210, 40),
                1,
                cv2.LINE_AA,
            )
    if camera.line:
        cv2.line(canvas, camera.line.start, camera.line.end, (0, 255, 255), 2)
    status = f"{camera.id} | DETECT {detect_fps:.1f} FPS"
    if prediction_age_ms is not None:
        mode = "TRACK STALE" if prediction_stale else "PRED"
        status += f" | {mode} {max(0, prediction_age_ms):.0f}ms"
    if camera.line:
        status += f" | A>B {counts['negative_to_positive']} B>A {counts['positive_to_negative']}"
    if camera.counting_region:
        status += f" | ENTER {counts['region_entries']} | INSIDE {counts['region_inside']}"
    (tw, _), _ = cv2.getTextSize(status, cv2.FONT_HERSHEY_SIMPLEX, 0.43, 1)
    # Leave the publisher's upper-right watermark visible in the highway clip.
    cv2.rectangle(canvas, (0, 0), (min(width, tw + 16), 30), (0, 0, 0), -1)
    cv2.putText(
        canvas, status, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.43, (255, 255, 255), 1, cv2.LINE_AA
    )
    footer = f"Zone alerts: {alert_count}"
    if video_seconds is not None:
        footer = f"{video_seconds:.1f}s | " + footer
    if camera.counting_region:
        footer += f" | First seen inside: {counts['region_first_seen_inside']} (not entry)"
    if active:
        footer += " | IN ZONE: " + ",".join(map(str, active[:10]))
    elif paused:
        footer += " | ZONE PAUSED"
    cv2.rectangle(canvas, (0, height - 26), (width, height), (0, 0, 0), -1)
    cv2.putText(
        canvas,
        footer,
        (8, height - 8),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.43,
        (0, 80, 255) if active else (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas
