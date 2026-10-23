from __future__ import annotations

import json
import logging
import time
from concurrent.futures import CancelledError, TimeoutError
from threading import Event, Lock, Thread

import cv2

from app.camera.capture import CameraCapture
from app.inference.scheduler import InferenceScheduler
from app.pipeline import AnalyticsPipeline
from app.streaming.publisher import FFmpegPublisher
from app.telemetry import clear_time, read_time, stamp_time

LOGGER = logging.getLogger(__name__)


class CameraWorker:
    def __init__(self, camera, config, scheduler, writer):
        self.camera, self.config = camera, config
        self.scheduler, self.writer = scheduler, writer
        self.pipeline = AnalyticsPipeline(camera)
        self.capture = CameraCapture(camera)
        self.stop_event, self.lock = Event(), Lock()
        self.publisher = None
        self.last_jpeg = None
        self.last_canvas = None
        self.canvas_sequence = 0
        self.jpeg_sequence = -1
        self.rendered = 0
        self.predicted_frames = 0
        self.tracked_rendered_frames = 0
        self.stale_tracking_frames = 0
        self.timings = {}
        self.error = None
        self.detected = 0
        self.detect_fps = 0
        self.internal_latency_ms = 0
        self.source_to_processed_ms = None
        self.source_timestamp_origin = None
        self.source_marker_frames = 0
        self.source_marker_misses = 0
        self.started = time.monotonic()
        self.thread = Thread(target=self._run, name=f"analytics-{camera.id}", daemon=True)

    def start(self):
        if self.config.streaming.enabled:
            self.publisher = FFmpegPublisher(self.config.streaming, self.camera.output_path)
        self.capture.start()
        self.thread.start()

    def _run(self):
        if self.config.model.async_inference:
            self._run_async()
            return
        sequence = 0
        window_start, window_frames = time.monotonic(), 0
        last_metrics = window_start
        while not self.stop_event.is_set():
            latest = self.capture.get_latest(sequence)
            if latest is None:
                if self.capture.eof:
                    return
                self.stop_event.wait(0.01)
                continue
            sequence, frame, seconds, captured_at = latest
            source_time = read_time(frame) if self.config.streaming.timestamp_overlay else None
            replay_marker_valid = source_time is not None
            self.source_timestamp_origin = "replay_marker" if source_time else "capture"
            if source_time is None:
                source_time = time.time() * 1000 - (time.monotonic() - captured_at) * 1000
            future = self.scheduler.submit(self.camera.id, frame)
            try:
                while True:
                    try:
                        detections = future.result(timeout=0.2)
                        break
                    except TimeoutError:
                        if self.stop_event.is_set():
                            self.scheduler.cancel(self.camera.id)
                            return
                if self.stop_event.is_set():
                    return
                now = time.monotonic()
                video_seconds = seconds if self.camera.source.type == "file" else None
                canvas, events, _ = self.pipeline.process(
                    frame,
                    detections,
                    seconds,
                    self.detect_fps,
                    video_seconds=video_seconds,
                )
                if self.config.streaming.timestamp_overlay:
                    if replay_marker_valid:
                        stamp_time(canvas, source_time)
                        self.source_marker_frames += 1
                    else:
                        clear_time(canvas)
                        self.source_marker_misses += 1
                for event in events:
                    self.writer.submit(event, canvas)
                if self.publisher:
                    self.publisher.submit(canvas)
                self._cache_canvas(canvas)
                self.detected += 1
                window_frames += 1
                self.internal_latency_ms = (time.monotonic() - captured_at) * 1000
                self.source_to_processed_ms = time.time() * 1000 - source_time
                if now - window_start >= 2:
                    self.detect_fps = window_frames / (now - window_start)
                    window_start, window_frames = now, 0
                self.error = None
                if now - last_metrics >= self.config.logging.metrics_interval_seconds:
                    LOGGER.info("camera_metrics %s", json.dumps(self.status()))
                    last_metrics = now
            except CancelledError:
                continue
            except Exception as exc:
                self.error = str(exc)
                LOGGER.exception("Camera processing failed: %s", self.camera.id)
                self.stop_event.wait(1)

    def _cache_canvas(self, canvas):
        # JPEG is encoded lazily by the API, never for an unused preview endpoint.
        with self.lock:
            self.last_canvas = canvas
            self.canvas_sequence += 1
        self.rendered += 1

    def jpeg(self):
        with self.lock:
            if self.last_canvas is None:
                return None
            if self.jpeg_sequence != self.canvas_sequence:
                ok, encoded = cv2.imencode(".jpg", self.last_canvas,
                                          [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    self.last_jpeg = encoded.tobytes()
                    self.jpeg_sequence = self.canvas_sequence
            return self.last_jpeg

    def _run_async(self):
        """One outstanding YOLO request; fresh-image rendering never waits on it."""
        pending = context = None
        sequence = last_submitted = 0
        render_due = 0.0
        window_start, window_frames = time.monotonic(), 0
        last_metrics = window_start
        while not self.stop_event.is_set():
            if pending is not None and pending.done():
                frame, seconds, captured_at, source_time, valid, submitted = context
                try:
                    detections = pending.result()
                    began = time.monotonic()
                    self.timings["inference_roundtrip_ms"] = (began - submitted) * 1000
                    video_seconds = seconds if self.camera.source.type == "file" else None
                    events, _ = self.pipeline.update(detections, seconds,
                                                     video_seconds=video_seconds)
                    self.timings["analytics_ms"] = (time.monotonic() - began) * 1000
                    if events:
                        evidence = self.pipeline.render(frame, seconds, self.detect_fps,
                                                        video_seconds=video_seconds)
                        for event in events:
                            self.writer.submit(event, evidence)
                    self.detected += 1
                    window_frames += 1
                    self.internal_latency_ms = (time.monotonic() - captured_at) * 1000
                    self.source_to_processed_ms = time.time() * 1000 - source_time
                    self.source_timestamp_origin = "replay_marker" if valid else "capture"
                    self.error = None
                except CancelledError:
                    pass
                except Exception as exc:
                    self.error = str(exc)
                    LOGGER.exception("Async inference failed: %s", self.camera.id)
                pending = context = None

            latest = self.capture.get_latest(sequence)
            now = time.monotonic()
            if latest is not None:
                current, frame, seconds, captured_at = latest
                if now >= render_due:
                    sequence = current
                    source_time = (read_time(frame)
                                   if self.config.streaming.timestamp_overlay else None)
                    valid = source_time is not None
                    if source_time is None:
                        source_time = time.time() * 1000 - (now - captured_at) * 1000
                    if pending is None and (not last_submitted or current - last_submitted
                                            >= self.config.model.detect_interval):
                        context = (frame, seconds, captured_at, source_time, valid, now)
                        pending = self.scheduler.submit(self.camera.id, frame)
                        last_submitted = current
                    began = time.monotonic()
                    video_seconds = seconds if self.camera.source.type == "file" else None
                    canvas = self.pipeline.render(frame, seconds, self.detect_fps,
                                                  video_seconds=video_seconds, predict=True,
                                                  output_size=(
                                                      self.config.streaming.max_output_width,
                                                      self.config.streaming.max_output_height))
                    self.timings["render_ms"] = (time.monotonic() - began) * 1000
                    if self.config.streaming.timestamp_overlay:
                        if valid:
                            stamp_time(canvas, source_time)
                            self.source_marker_frames += 1
                        else:
                            clear_time(canvas)
                            self.source_marker_misses += 1
                    began = time.monotonic()
                    if self.publisher:
                        self.publisher.submit(canvas)
                    self.timings["publisher_submit_ms"] = (time.monotonic() - began) * 1000
                    self._cache_canvas(canvas)
                    has_tracks = bool(self.pipeline.last_render_tracks)
                    observation = self.pipeline.last_observation
                    self.tracked_rendered_frames += int(has_tracks)
                    self.predicted_frames += int(has_tracks and observation is not None
                                                 and seconds != observation)
                    self.stale_tracking_frames += int(observation is not None and
                        (seconds - observation) * 1000 > self.camera.prediction_max_age_ms)
                    render_due = max(render_due + 1 / self.config.streaming.output_fps, now)
            elif self.capture.eof and pending is None:
                return
            if now - window_start >= 2:
                self.detect_fps = window_frames / (now - window_start)
                window_start, window_frames = now, 0
            if now - last_metrics >= self.config.logging.metrics_interval_seconds:
                LOGGER.info("camera_metrics %s", json.dumps(self.status()))
                last_metrics = now
            self.stop_event.wait(0.003)

    def status(self):
        elapsed = max(0.001, time.monotonic() - self.started)
        publisher = self.publisher
        return {
            "id": self.camera.id,
            "enabled": True,
            "session_id": self.pipeline.session_id,
            "eof": self.capture.eof,
            "capture_sequence": self.capture.sequence,
            "processed_frames": self.detected,
            "rendered_frames": self.rendered,
            "predicted_frames": self.predicted_frames,
            "tracked_rendered_frames": self.tracked_rendered_frames,
            "stale_tracking_frames": self.stale_tracking_frames,
            "async_inference": self.config.model.async_inference,
            "stage_last_ms": {key: round(value, 2) for key, value in self.timings.items()},
            "model_batch_last_ms": round(self.scheduler.last_batch_ms, 2),
            "model_last_batch_frames": self.scheduler.last_batch_frames,
            "model_stage_ms": getattr(self.scheduler.detector, "last_profile_ms", {}),
            "model_mode": self.config.model.instances,
            "model_instance": self.camera.id
            if self.config.model.instances == "per_camera" else "shared",
            "dedicated_cuda_stream": getattr(self.scheduler.detector, "_cuda_stream", None)
            is not None,
            "detect_fps": round(self.detect_fps or self.detected / elapsed, 2),
            "internal_latency_ms": round(self.internal_latency_ms, 1),
            "source_to_processed_ms": round(self.source_to_processed_ms, 1)
            if self.source_to_processed_ms is not None else None,
            "source_latency_basis": "replay marker or capture timestamp; excludes output decode",
            "source_timestamp_origin": self.source_timestamp_origin,
            "source_marker_frames": self.source_marker_frames,
            "source_marker_misses": self.source_marker_misses,
            "reconnect_count": self.capture.reconnect_count,
            "capture_open_attempts": self.capture.open_attempts,
            "counts": dict(self.pipeline.processor.counts),
            "zone_alerts": self.pipeline.alert_count,
            "error": self.error,
            "capture_error": self.capture.error,
            "publisher_error": publisher.error if publisher else None,
            "output_frames": publisher.frames if publisher else 0,
            "unique_output_frames": publisher.unique_frames if publisher else 0,
            "publisher_restarts": publisher.restarts if publisher else 0,
            "publisher_pid": publisher.process.pid if publisher and publisher.process else None,
            "publisher_alive": publisher.thread.is_alive() if publisher else False,
            "encoder": publisher.encoder if publisher else None,
            "encoder_diagnostic": publisher.encoder_diagnostic if publisher else None,
        }

    def close(self):
        self.stop_event.set()
        self.scheduler.cancel(self.camera.id)
        self.thread.join(timeout=10)
        self.capture.close()
        if self.publisher:
            self.publisher.close()


class CameraManager:
    def __init__(self, config, detector, writer, *, detector_factory=None):
        self.config, self.writer = config, writer
        self.detector = detector
        self.detector_factory = detector_factory
        if self.detector_factory is None:
            builder = getattr(detector, "clone_factory", None)
            self.detector_factory = builder() if builder else getattr(detector, "clone", None)
        self.prototype_available = True
        self.schedulers = {}
        self.scheduler = None
        if config.model.instances == "shared":
            self.scheduler = InferenceScheduler(
                detector, config.model.batch_size, config.model.batch_wait_ms,
                warmup=config.model.async_inference and hasattr(detector, "warmup"),
            )
        elif self.detector_factory is None:
            raise ValueError("per_camera mode requires detector.clone() or detector_factory")
        self.workers = {}
        self.lock = Lock()

    def start(self):
        try:
            # Load/warm models sequentially before capture/render threads contend for RAM/CPU.
            if self.config.model.instances == "per_camera":
                for camera in self.config.cameras:
                    if camera.enabled:
                        self._scheduler_for(camera.id)
            for camera in self.config.cameras:
                if camera.enabled:
                    self.set_enabled(camera.id, True)
        except Exception:
            self.close()
            raise

    def _scheduler_for(self, camera_id):
        if self.scheduler is not None:
            return self.scheduler
        if camera_id not in self.schedulers:
            detector = self.detector if self.prototype_available else self.detector_factory()
            if self.prototype_available:
                self.detector = None
            self.prototype_available = False
            if hasattr(detector, "load"):
                detector.load()
            self.schedulers[camera_id] = InferenceScheduler(
                detector, 1, 0, warmup=hasattr(detector, "warmup"))
        return self.schedulers[camera_id]

    def _camera(self, camera_id):
        for camera in self.config.cameras:
            if camera.id == camera_id:
                return camera
        raise KeyError(camera_id)

    def set_enabled(self, camera_id, enabled):
        with self.lock:
            camera = self._camera(camera_id)
            if enabled and camera_id not in self.workers:
                worker = CameraWorker(camera, self.config,
                                      self._scheduler_for(camera.id), self.writer)
                worker.start()
                self.workers[camera_id] = worker
            elif not enabled and camera_id in self.workers:
                self.workers.pop(camera_id).close()
                scheduler = self.schedulers.pop(camera_id, None)
                if scheduler:
                    scheduler.close()
            return self._status(camera)

    def _status(self, camera):
        worker = self.workers.get(camera.id)
        return worker.status() if worker else {"id": camera.id, "enabled": False}

    def statuses(self):
        with self.lock:
            return [self._status(camera) for camera in self.config.cameras]

    def latest_jpeg(self, camera_id):
        with self.lock:
            self._camera(camera_id)
            worker = self.workers.get(camera_id)
            if worker:
                return worker.jpeg()
        return None

    def close(self):
        with self.lock:
            for worker in self.workers.values():
                worker.close()
            self.workers.clear()
        if self.scheduler:
            self.scheduler.close()
        for scheduler in self.schedulers.values():
            scheduler.close()
        self.schedulers.clear()
