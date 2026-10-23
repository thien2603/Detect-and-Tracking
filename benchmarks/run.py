"""Measure RTSP output with a shared serial/batch model or independent camera models."""

import argparse
import json
import logging
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from urllib.request import urlopen

import cv2
import numpy as np
import psutil
import yaml

from app.telemetry import console_logging
from benchmarks.probe import RTSPProbe
from scripts.run_realtime import RuntimeStack, add_arguments

LOGGER = logging.getLogger(__name__)


def gpu_snapshot():
    """Whole-GPU readings, including display/other apps; not per-process allocation."""
    try:
        result = subprocess.run([
            "nvidia-smi", "--query-gpu=index,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ], capture_output=True, text=True, timeout=3)
        if result.returncode:
            return []
        return [dict(zip(("index", "memory_used_mib", "memory_free_mib", "utilization_percent"),
                         (int(value.strip()) for value in line.split(",")), strict=True))
                for line in result.stdout.strip().splitlines() if line.strip()]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def machine_info():
    info = {"os": platform.platform(), "python": platform.python_version(),
            "cpu": platform.processor(), "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(), "ram_bytes": psutil.virtual_memory().total}
    if shutil.which("nvidia-smi"):
        result = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                                 "--format=csv,noheader"], capture_output=True,
                                text=True, timeout=5)
        info["gpu"] = result.stdout.strip() if result.returncode == 0 else None
    return info


def get_cameras(api):
    with urlopen(api + "/api/v1/cameras", timeout=5) as response:
        return json.load(response)


def scenario(args, count, strategy):
    directory = args.output / f"{count}cam-{strategy}"
    stack = RuntimeStack(args, count=count, batch_size=4 if strategy == "batch" else 1,
                         output=directory,
                         model_mode="per_camera"
                         if strategy.startswith("independent") else "shared",
                         cuda_streams=strategy == "independent_streams")
    probes = []
    samples = []
    tracked = {}
    try:
        stack.start()
        LOGGER.info("Warming up %d cameras, strategy=%s", count, strategy)
        deadline = time.monotonic() + args.startup_timeout
        while True:
            cameras = get_cameras(stack.api)
            if len(cameras) == count and all(c.get("processed_frames", 0) >= 5 for c in cameras):
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Not all cameras produced detections before startup timeout")
            time.sleep(0.5)
        config = yaml.safe_load(stack.config_path.read_text())
        for camera in config["cameras"]:
            probes.append(RTSPProbe(stack.rtsp + "/processed/" + camera["output_path"],
                                    ffmpeg=args.ffmpeg if args.probe_backend == "ffmpeg" else None))
        time.sleep(args.warmup)
        before = {camera["id"]: camera for camera in get_cameras(stack.api)}
        start = time.monotonic()
        while time.monotonic() - start < args.seconds:
            root = psutil.Process()
            processes = [root, *root.children(recursive=True)]
            cpu, ram = 0.0, 0
            for process in processes:
                try:
                    instance = tracked.setdefault(process.pid, process)
                    cpu += instance.cpu_percent(None)
                    ram += instance.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            cameras = get_cameras(stack.api)
            samples.append({"elapsed": time.monotonic() - start, "cpu_percent_sum": cpu,
                            "rss_bytes_sum": ram, "cameras": cameras,
                            "available_ram_mb": psutil.virtual_memory().available / 1024**2,
                            "gpus": gpu_snapshot() if args.sample_gpu else []})
            if samples[-1]["available_ram_mb"] < args.min_runtime_free_ram_mb:
                raise RuntimeError("Resource guard: available RAM below runtime minimum")
            if any(gpu["memory_free_mib"] < 256 for gpu in samples[-1]["gpus"]):
                raise RuntimeError("Resource guard: less than 256 MiB free VRAM")
            LOGGER.info("%dcam/%s measured %.1f/%.1fs", count, strategy,
                        time.monotonic() - start, args.seconds)
            time.sleep(min(2, max(0, args.seconds - (time.monotonic() - start))))
        end = time.monotonic()
        final = {camera["id"]: camera for camera in get_cameras(stack.api)}
        results = []
        for camera, probe in zip(config["cameras"], probes, strict=True):
            key = camera["id"]
            measurement = probe.report(start, end)
            measurement.update({"id": key,
                                "detect_fps": (final[key]["processed_frames"]
                                               - before[key]["processed_frames"]) / (end - start),
                                "camera_status": final[key]})
            measurement["render_fps"] = (final[key].get("rendered_frames", 0)
                                         - before[key].get("rendered_frames", 0)) / (end - start)
            measurement["stale_tracking_frames"] = (
                final[key].get("stale_tracking_frames", 0)
                - before[key].get("stale_tracking_frames", 0))
            detection_ages = [c["source_to_processed_ms"] for sample in samples
                              for c in sample["cameras"] if c["id"] == key
                              and c.get("source_to_processed_ms") is not None]
            measurement["sampled_detection_age_max_ms"] = max(detection_ages, default=None)
            measurement["timestamp_coverage"] = (measurement["timestamp_samples"]
                                                  / max(1, measurement["decoded_frames"]))
            valid_markers = (final[key]["source_marker_frames"]
                             - before[key]["source_marker_frames"])
            missing_markers = (final[key]["source_marker_misses"]
                               - before[key]["source_marker_misses"])
            measurement["source_marker_coverage"] = valid_markers / max(
                1, valid_markers + missing_markers)
            measurement["meets_10fps"] = measurement["decoded_fps"] >= 10
            measurement["meets_10_unique_fps"] = measurement["unique_source_fps"] >= 10
            measurement["meets_latency"] = (measurement["latency_max_ms"] is not None
                                             and measurement["latency_max_ms"] < 1000
                                             and measurement["timestamp_coverage"] >= 0.95
                                             and measurement["source_marker_coverage"] >= 0.95)
            results.append(measurement)
        frames = [probe.last_frame for probe in probes[:4] if probe.last_frame is not None]
        if len(frames) >= 4:
            tiles = [cv2.resize(frame, (640, 360)) for frame in frames[:4]]
            cv2.imwrite(str(directory / "simultaneous-preview.jpg"),
                        np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])]))
        report = {"camera_count": count, "strategy": strategy, "seconds": end - start,
                  "optimized": config["model"].get("async_inference", False),
                  "model_mode": config["model"]["instances"],
                  "model_instances": count if strategy.startswith("independent") else 1,
                  "dedicated_cuda_streams": config["model"]["cuda_streams"],
                  "fps_definitions": {"detect_fps": "completed measured YOLO frames per camera",
                                      "render_fps": "new source images, possibly predicted tracks",
                                      "decoded_fps": "decoded output; may repeat cached images",
                                      "unique_source_fps": "distinct source timestamps decoded"},
                  "latency_scope": "Replay capture to decoded RTSP output, not VLC display",
                  "source_diversity": "Logical streams drawn from the supplied base config; "
                                      "extra streams repeat videos; see configs/service.yaml.",
                  "cpu_mean_percent_sum": float(np.mean([s["cpu_percent_sum"]
                                                          for s in samples[1:]]))
                  if len(samples) > 1 else None,
                  "peak_rss_bytes_sum": max(s["rss_bytes_sum"] for s in samples),
                  "gpu_memory_peak_mib": max((gpu["memory_used_mib"] for sample in samples
                                              for gpu in sample["gpus"]), default=None),
                  "minimum_available_ram_mb": min(s["available_ram_mb"] for s in samples),
                  "cameras": results, "samples": samples}
        (directory / "measurement.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
    finally:
        for probe in probes:
            probe.close()
        stack.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--counts", nargs="+", type=int, default=[1, 4, 8], choices=[1, 4, 8])
    parser.add_argument("--strategies", nargs="+", default=["serial", "batch"],
                        choices=["serial", "batch", "independent", "independent_streams"])
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--warmup", type=float, default=5)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("--min-free-ram-mb", type=int, default=1800)
    parser.add_argument("--min-runtime-free-ram-mb", type=int, default=256)
    parser.add_argument("--sample-gpu", action="store_true")
    parser.add_argument("--probe-backend", choices=["ffmpeg", "opencv"], default="ffmpeg")
    args = parser.parse_args()
    if args.seconds < 10 or args.warmup < 0:
        parser.error("Use at least 10 measured seconds and a non-negative warmup")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "benchmark.json"
    if summary_path.exists():
        raise FileExistsError("Choose a new benchmark directory")
    console_logging()
    cv2.setNumThreads(1)
    # Match the service transport: default UDP probes may lose packets even when
    # the actual publishers/captures use TCP. Set once before probe threads start.
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                          "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|"
                          "analyzeduration;0|probesize;32768")
    summary = {"created_at": datetime.now(timezone.utc).isoformat(),
               "machine": machine_info(), "results": []}
    available_mb = psutil.virtual_memory().available / 1024**2
    summary["preflight"] = {"free_ram_mb": available_mb,
                            "minimum_ram_mb": args.min_free_ram_mb}
    if available_mb < args.min_free_ram_mb:
        summary["status"] = "blocked_insufficient_free_memory"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        LOGGER.error("Only %.0f MB RAM available; need at least %d MB before loading YOLO. "
                     "No benchmark result was fabricated.", available_mb, args.min_free_ram_mb)
        raise SystemExit(2)
    for count in args.counts:
        for strategy in args.strategies:
            try:
                if psutil.virtual_memory().available / 1024**2 < args.min_free_ram_mb:
                    raise RuntimeError("Scenario preflight: insufficient available RAM")
                result = scenario(args, count, strategy)
                result["status"] = "completed"
            except Exception as exc:
                LOGGER.exception("Failed scenario %dcam/%s", count, strategy)
                result = {"camera_count": count, "strategy": strategy, "status": "failed",
                          "error": f"{type(exc).__name__}: {exc}"}
            summary["results"].append(result)
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["status"] = ("completed" if all(r["status"] == "completed"
                                          for r in summary["results"]) else "incomplete")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    LOGGER.info("Benchmark complete: %s", summary_path)


if __name__ == "__main__":
    main()
