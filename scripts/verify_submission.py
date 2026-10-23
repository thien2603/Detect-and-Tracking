"""Verify submitted artifacts, preserving a separate false status for unmet NFRs."""

import argparse
import json
import logging
import sqlite3
from collections import Counter
from pathlib import Path

from scripts.prepare_bellevue import inspect_clip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--folder", type=Path, default=Path("output/submission/TranDanhThien"))
    parser.add_argument("--run", type=Path, default=Path("data/live-demo-02"))
    parser.add_argument("--output", type=Path, default=Path("data/verification/submission.json"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.output.exists():
        raise FileExistsError("Choose a new verification output")
    video = args.folder / "Demo_TranDanhThien.mp4"
    pdf = args.folder / "BaoCao_TranDanhThien.pdf"
    metadata = json.loads(video.with_suffix(".json").read_text())
    assert metadata["timing"].startswith("VFR")
    assert metadata["not_a_benchmark"] is True
    assert len(set(metadata["camera_ids"])) == 4
    assert all(probe["decoded_frames"] > 0 for probe in metadata["probes"])
    assert len(metadata["sample_timestamps_seconds"]) == metadata["frames"]
    assert pdf.is_file() and pdf.stat().st_size > 1000
    # Decode every frame, inspect actual container duration, and hash the final MP4.
    decoded = inspect_clip(args.ffmpeg, video.resolve(), round(metadata["video_seconds"]))
    uri = (args.run / "events.db").resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as database:
        events = [json.loads(row[0]) for row in database.execute(
            "SELECT payload FROM events WHERE occurred_at>=? AND occurred_at<=?",
            (metadata["recording_started_at"], metadata["recording_ended_at"]),
        )]
    assert events, "Demo must include actual events while live frames were being recorded"
    assert all(Path(event["snapshot"]).is_file() for event in events)
    cleanup = json.loads((args.run / "cleanup.json").read_text())
    assert not cleanup["remaining_descendants"]
    api_log = (args.run / "api.log").read_text(encoding="utf-8", errors="replace")
    service_log = (args.run / "service.log").read_text(encoding="utf-8", errors="replace")
    shutdown_lifespan_complete = ("Application shutdown complete" in api_log
                                 and "Camera workers and inference scheduler stopped"
                                 in service_log)
    # A Windows Uvicorn SIGINT re-raise can produce nonzero exit after clean shutdown.
    # Keep raw exit flags and verify the actual resource/lifespan evidence separately.
    assert all(cleanup["graceful_exit"].values()) or shutdown_lifespan_complete
    benchmark = json.loads(Path("data/benchmark-submission-02/benchmark.json").read_text())
    pairs = {(r["camera_count"], r["strategy"]) for r in benchmark["results"]
             if r.get("status") == "completed" and len(r.get("cameras", [])) == r["camera_count"]}
    assert pairs == {(count, strategy) for count in (1, 4, 8) for strategy in ("serial", "batch")}
    final = json.loads(Path("data/benchmark-final-4cam/benchmark.json").read_text())
    nfr_pass = any(all(c["meets_10fps"] and c["meets_latency"] for c in r.get("cameras", []))
                   for r in final["results"] if len(r.get("cameras", [])) == 4)
    report = {
        "artifact_checks_passed": True, "all_assignment_criteria_passed": False,
        "demo_decode": decoded, "demo_wall_seconds": metadata["wall_seconds"],
        "events_during_demo": len(events),
        "events_by_camera": dict(Counter(e["camera_id"] for e in events)),
        "event_types": dict(Counter(e["event_type"] for e in events)),
        "six_scenarios_measured": True, "four_camera_nfr_passed": nfr_pass,
        "cleanup": cleanup,
        "shutdown_lifespan_complete": shutdown_lifespan_complete,
        "remaining": ["4-camera FPS/latency target", "Docker runtime", "physical webcam",
                      "VLC GUI", "GitHub push/verification", "Google Drive submission"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logging.info("Artifact checks passed, %d demo-time events. Full criteria passed: False",
                 len(events))


if __name__ == "__main__":
    main()
