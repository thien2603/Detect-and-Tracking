"""Fit and preview Bellevue counting/alert polygons without running detection.

The percentages refer to pixel area in a manually selected visible intersection,
not calibrated ground-plane area. This is a geometry-preparation tool; the current
application uses configs/bellevue.yaml to enable the approved region counter.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import cv2
import numpy as np

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
GREEN = (70, 215, 70)
RED = (45, 45, 245)


def area(points):
    """Shoelace area, allowing floating-point vertices during fitting."""
    return abs(sum(
        x * points[(i + 1) % len(points)][1]
        - points[(i + 1) % len(points)][0] * y
        for i, (x, y) in enumerate(points)
    )) / 2


def split_intersection(points, count_fraction=0.75):
    """Split a clockwise convex quad along corresponding top/bottom edges."""
    if len(points) != 4 or not 0 < count_fraction < 1:
        raise ValueError("Expected four vertices and a fraction between zero and one")
    quad = np.asarray(points, dtype=np.float32)
    if not cv2.isContourConvex(quad) or area(points) == 0:
        raise ValueError("Intersection must be a non-degenerate convex quadrilateral")
    a, b, c, d = quad.astype(float)
    low, high = 0.0, 1.0
    target = area(points) * count_fraction
    for _ in range(60):
        t = (low + high) / 2
        p, q = a + t * (b - a), d + t * (c - d)
        if area([a, p, q, d]) < target:
            low = t
        else:
            high = t
    t = (low + high) / 2
    p = np.rint(a + t * (b - a)).astype(int).tolist()
    q = np.rint(d + t * (c - d)).astype(int).tolist()
    count = [points[0], p, q, points[3]]
    alert = [p, points[1], points[2], q]
    total = area(count) + area(alert)
    # Rounding a boundary vertex can move it slightly off the original edge.
    # Check both the split fraction and the union against the selected quad.
    if abs(area(count) / total - count_fraction) > 0.004:
        raise ValueError("Pixel rounding exceeds area-ratio tolerance")
    if abs(total - area(points)) / area(points) > 0.004:
        raise ValueError("Partition does not cover the selected intersection")
    overlap, _ = cv2.intersectConvexConvex(
        np.array(count, np.float32), np.array(alert, np.float32)
    )
    if overlap > 1:
        raise ValueError("Counting and alert regions must not overlap")
    return count, alert


def frame_at(capture, seconds):
    capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"Cannot read video frame at {seconds}s")
    return frame


def label(canvas, text, origin, color):
    x, y = origin
    (width, height), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    cv2.rectangle(canvas, (x - 5, y - height - 5),
                  (x + width + 5, y + baseline + 4), (18, 18, 18), -1)
    cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                color, 2, cv2.LINE_AA)


def draw(frame, camera_id, intersection, count, alert, seconds):
    canvas = frame.copy()
    overlay = canvas.copy()
    for polygon, color in ((count, GREEN), (alert, RED)):
        cv2.fillPoly(overlay, [np.array(polygon, np.int32)], color)
    canvas = cv2.addWeighted(overlay, 0.24, canvas, 0.76, 0)
    for polygon, color in ((count, GREEN), (alert, RED)):
        cv2.polylines(canvas, [np.array(polygon, np.int32)], True, color, 3, cv2.LINE_AA)
    for i, point in enumerate(intersection, 1):
        cv2.circle(canvas, tuple(point), 5, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.putText(canvas, str(i), (point[0] + 7, point[1] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    total = area(count) + area(alert)
    count_percent, alert_percent = area(count) / total * 100, area(alert) / total * 100
    # Keep labels above the road instead of covering vehicles or the source timestamp.
    cv2.rectangle(canvas, (0, 0), (frame.shape[1], 78), (18, 18, 18), -1)
    label(canvas, f"{camera_id.upper()} | {seconds:g}s | GEOMETRY PREVIEW - NO DETECTION",
          (14, 26), (245, 245, 245))
    label(canvas, f"COUNT REGION {count_percent:.1f}%", (14, 61), GREEN)
    label(canvas, f"ALERT ZONE {alert_percent:.1f}%", (390, 61), RED)
    return canvas


def save(path, frame):
    if not cv2.imwrite(str(path), frame):
        raise OSError(f"Cannot write {path}")


def prepare(layout, output, coordinates):
    if layout.get("alert_side") != "right":
        raise ValueError("This layout supports a right-side alert partition")
    output.mkdir(parents=True, exist_ok=True)
    coordinates.parent.mkdir(parents=True, exist_ok=True)
    expected_size = tuple(layout["frame_size"])
    results, overview = [], []
    for camera in layout["cameras"]:
        intersection = camera["intersection"]
        for x, y in intersection:
            if not 0 <= x < expected_size[0] or not 0 <= y < expected_size[1]:
                raise ValueError(f"Vertex outside source frame: {camera['id']}")
        count, alert = split_intersection(intersection, layout["count_fraction"])
        capture = cv2.VideoCapture(str(ROOT / camera["source"]))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {camera['source']}")
        try:
            preview = frame_at(capture, layout["preview_seconds"])
            if (preview.shape[1], preview.shape[0]) != expected_size:
                raise ValueError(
                    "Video size differs from region coordinates; do not rescale silently"
                )
            preview = draw(preview, camera["id"], intersection, count, alert,
                           layout["preview_seconds"])
            save(output / f"{camera['id']}-zones.jpg", preview)
            overview.append(cv2.resize(preview, (768, 432)))
            samples = []
            for seconds in (0, 90, 179):
                sample = draw(frame_at(capture, seconds), camera["id"], intersection,
                              count, alert, seconds)
                samples.append(cv2.resize(sample, (640, 360)))
            save(output / f"{camera['id']}-timeline.jpg", np.hstack(samples))
        finally:
            capture.release()
        total = area(count) + area(alert)
        result = {
            "camera_id": camera["id"], "source": camera["source"],
            "frame_size": list(expected_size),
            "detection_region": {"id": "intersection", "points": intersection},
            "counting_region": {"id": "count_75", "points": count},
            "forbidden_zones": [{"id": "alert_25_demo", "points": alert}],
            "count_area_percent": round(area(count) / total * 100, 3),
            "alert_area_percent": round(area(alert) / total * 100, 3),
        }
        results.append(result)
        LOGGER.info("%s: count=%s%%, alert=%s%%", camera["id"],
                    result["count_area_percent"], result["alert_area_percent"])
    contact_sheet = np.vstack([np.hstack(overview[:2]), np.hstack(overview[2:])])
    save(output / "overview.jpg", contact_sheet)
    coordinates.write_text(json.dumps({
        "status": "region_geometry_reference_not_runtime_app_config",
        "area_basis": "pixel area of each manually selected intersection; not real-world area",
        "counting_note": "Approved polygons are connected through configs/bellevue.yaml. "
                         "One observed outside-to-inside entry is counted per track ID.",
        "alert_note": "Demonstration alert zones, not evidence of actual road restrictions.",
        "cameras": results,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("Preview: %s", output / "overview.jpg")
    LOGGER.info("Coordinates: %s", coordinates)


def main():
    console_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", type=Path, default=ROOT / "configs/bellevue-region-layout.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/bellevue-zones")
    parser.add_argument("--coordinates", type=Path, default=ROOT / "configs/bellevue-regions.json")
    args = parser.parse_args()
    prepare(json.loads(args.layout.read_text(encoding="utf-8")), args.output, args.coordinates)


if __name__ == "__main__":
    main()
