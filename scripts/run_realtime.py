"""Start loopback MediaMTX, file replays and the 4-camera service together."""

import argparse
import contextlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from urllib.request import urlopen

import yaml

from app.config.loader import load_config
from app.telemetry import console_logging
from scripts.prepare_realtime_config import ROOT, build_config, save_config

LOGGER = logging.getLogger(__name__)


class RuntimeStack:
    def __init__(self, args, *, count=None, batch_size=4, output=None, model_mode=None,
                 cuda_streams=None):
        self.args = args
        self.output = Path(output or args.output).resolve()
        if self.output.exists() and any(self.output.iterdir()):
            raise FileExistsError(f"Choose a new run directory: {self.output}")
        self.output.mkdir(parents=True, exist_ok=True)
        self.count, self.batch_size = count, batch_size
        self.model_mode = model_mode
        self.cuda_streams = cuda_streams
        self.processes = []
        self.logs = []
        self.stop_file = self.output / "stop.signal"
        self.api = f"http://127.0.0.1:{args.api_port}"
        self.rtsp = f"rtsp://127.0.0.1:{args.rtsp_port}"

    def start_process(self, command, name, env):
        log = (self.output / f"{name}.log").open("w", encoding="utf-8")
        self.logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                   stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process

    def start(self):
        for port in (self.args.api_port, self.args.rtsp_port):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
        config = build_config(load_config(self.args.config), self.count,
                              rtsp_server=self.rtsp, batch_size=self.batch_size,
                              output=self.output, device=self.args.device)
        self.count = len(config["cameras"])
        config["streaming"]["ffmpeg_bin"] = str(Path(self.args.ffmpeg).resolve())
        if getattr(self.args, "encode_ffmpeg", None):
            config["streaming"]["ffmpeg_bin"] = str(Path(self.args.encode_ffmpeg).resolve())
        if getattr(self.args, "encoder", None):
            config["streaming"]["encoder"] = self.args.encoder
        if getattr(self.args, "optimized", False):
            config["model"].update(async_inference=True, detect_interval=2, half=True,
                                   rect=False, batch_wait_ms=15)
            config["streaming"]["output_fps"] = 14
            for camera in config["cameras"]:
                camera.update(tracker_motion=True, prediction_max_age_ms=700)
        mode = self.model_mode or getattr(self.args, "model_mode", None)
        if mode:
            config["model"]["instances"] = mode
        if config["model"]["instances"] == "per_camera":
            config["model"].update(batch_size=1, batch_wait_ms=0)
        if getattr(self.args, "square_input", False):
            config["model"]["rect"] = False
        if self.cuda_streams is not None:
            config["model"]["cuda_streams"] = self.cuda_streams
        elif getattr(self.args, "cuda_streams", False):
            config["model"]["cuda_streams"] = True
        self.config_path = self.output / "configs" / "service.yaml"
        save_config(config, self.config_path)
        server_config = self.output / "mediamtx.yaml"
        server_config.write_text(yaml.safe_dump({
            "logLevel": "warn", "rtsp": True,
            "rtspAddress": f"127.0.0.1:{self.args.rtsp_port}", "protocols": ["tcp"],
            "rtmp": False, "hls": False, "webrtc": False, "srt": False,
            "paths": {"all_others": None},
        }), encoding="utf-8")
        env = os.environ.copy()
        env["OPENCV_FFMPEG_THREADS"] = "1"
        env["OMP_NUM_THREADS"] = "2"
        env["OPENBLAS_NUM_THREADS"] = "1"
        # These low-buffer decoder options apply only to child processes of this run.
        env["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|analyzeduration;0|probesize;32768"
        )
        env["CONFIG_PATH"] = str(self.config_path)
        self.start_process([self.args.mediamtx, str(server_config)], "mediamtx", env)
        deadline = time.monotonic() + 10
        while True:
            try:
                with socket.create_connection(("127.0.0.1", self.args.rtsp_port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("MediaMTX did not start; inspect its log") from None
                time.sleep(0.1)
        self.replay = self.start_process([
            sys.executable, "-m", "scripts.replay_rtsp", "--config", self.args.config,
            "--server", self.rtsp, "--ffmpeg", self.args.ffmpeg, "--count", str(self.count),
            "--stop-file", str(self.stop_file),
        ], "replay", env)
        self.service = self.start_process([
            sys.executable, "-m", "scripts.serve", "--host", "127.0.0.1",
            "--port", str(self.args.api_port), "--stop-file", str(self.stop_file),
        ], "api", env)
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in self.processes):
                raise RuntimeError("A service exited during startup; inspect run logs")
            try:
                with urlopen(self.api + "/health", timeout=1) as response:
                    if response.status == 200:
                        LOGGER.info("Service ready: %s/docs", self.api)
                        return self
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("API startup timed out")

    def close(self):
        # Ask the app/replays to stop through their own finally/lifespan blocks first.
        import psutil

        descendants = []
        for process in self.processes:
            with contextlib.suppress(psutil.NoSuchProcess):
                descendants.extend(psutil.Process(process.pid).children(recursive=True))
        self.stop_file.touch()
        graceful = {}
        for name in ("service", "replay"):
            process = getattr(self, name, None)
            if process:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=20)
                graceful[name] = process.poll() == 0
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        # Windows terminate() does not run child finally blocks. Reap only our descendants.
        for child in descendants:
            try:
                child.terminate()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
            except psutil.TimeoutExpired:
                child.kill()
        for log in self.logs:
            log.close()
        remaining = [child.pid for child in descendants if child.is_running()]
        (self.output / "cleanup.json").write_text(json.dumps({
            "owned_processes": [p.pid for p in self.processes],
            "remaining_descendants": remaining,
            "graceful_exit": graceful,
        }, indent=2), encoding="utf-8")
        if remaining:
            raise RuntimeError(f"Owned processes did not stop: {remaining}")


def add_arguments(parser):
    parser.add_argument("--config", default=str(ROOT / "configs/bellevue.yaml"))
    parser.add_argument("--mediamtx", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--device", default="0")
    parser.add_argument("--model-mode", choices=["shared", "per_camera"])
    parser.add_argument("--cuda-streams", action="store_true",
                        help="Per-detector CUDA stream; backend sync may limit overlap")
    parser.add_argument("--square-input", action="store_true",
                        help="Use equal square input geometry for fair model-mode comparisons")
    parser.add_argument("--encode-ffmpeg",
                        help="Output encoder binary; probes/replay unchanged")
    parser.add_argument("--encoder", choices=["libx264", "h264_nvenc", "auto"])
    parser.add_argument("--optimized", action="store_true",
                        help="Async rendering, bounded Kalman display predictions, FP16")
    parser.add_argument("--api-port", type=int, default=18000)
    parser.add_argument("--rtsp-port", type=int, default=18554)
    parser.add_argument("--output", type=Path, default=ROOT / "data/realtime/current")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    args = parser.parse_args()
    console_logging()
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    stack = RuntimeStack(args)
    try:
        stack.start()
        # Some Windows terminal hosts deliver Ctrl+C to children before their
        # Python launcher. Do not leave the coordinator waiting after children exit.
        while not stopped.wait(0.2):
            if stack.stop_file.exists():
                break
            if any(process.poll() is not None for process in stack.processes):
                LOGGER.warning("A runtime child exited; shutting down the owned stack")
                break
    finally:
        stack.close()


if __name__ == "__main__":
    main()
