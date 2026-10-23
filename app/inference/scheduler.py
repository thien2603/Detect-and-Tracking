from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from threading import Condition, Event, Thread
from time import monotonic


class InferenceScheduler:
    """Bounded, fair queue: at most one pending request per camera, one model thread."""

    def __init__(self, detector, batch_size=1, batch_wait_ms=0, warmup=False):
        self.detector = detector
        self.batch_size = batch_size
        self.batch_wait_seconds = batch_wait_ms / 1000
        self.batches = 0
        self.frames = 0
        self.last_batch_ms = 0.0
        self.last_batch_frames = 0
        self.ready = Event()
        self.startup_error = None
        self.warmup = warmup
        self.pending = OrderedDict()
        self.condition = Condition()
        self.closed = False
        self.thread = Thread(target=self._run, name="inference", daemon=True)
        self.thread.start()
        if warmup:
            if not self.ready.wait(90):
                self.close()
                raise RuntimeError("Inference warmup timed out")
            if self.startup_error:
                self.close()
                raise RuntimeError(f"Inference warmup failed: {self.startup_error}")

    def submit(self, camera_id, frame):
        future = Future()
        with self.condition:
            if self.closed:
                future.set_exception(RuntimeError("scheduler stopped"))
                return future
            old = self.pending.pop(camera_id, None)
            if old:
                old[1].cancel()
            self.pending[camera_id] = (frame, future)
            self.condition.notify()
        return future

    def cancel(self, camera_id):
        with self.condition:
            old = self.pending.pop(camera_id, None)
            if old:
                old[1].cancel()

    def _run(self):
        try:
            if self.warmup:
                self.detector.warmup(self.batch_size)
        except Exception as exc:
            self.startup_error = exc
            return
        finally:
            self.ready.set()
        self._serve()

    def _serve(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.closed or self.pending)
                if self.closed:
                    return
                deadline = monotonic() + self.batch_wait_seconds
                while len(self.pending) < self.batch_size and not self.closed:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
                    self.condition.wait(timeout=remaining)
                if self.closed:
                    return
                requests = []
                while self.pending and len(requests) < self.batch_size:
                    _, (frame, future) = self.pending.popitem(last=False)
                    if future.set_running_or_notify_cancel():
                        requests.append((frame, future))
            if not requests:
                continue
            try:
                started = monotonic()
                results = self.detector.detect_batch([frame for frame, _ in requests])
                self.last_batch_ms = (monotonic() - started) * 1000
                self.last_batch_frames = len(requests)
                self.batches += 1
                self.frames += len(requests)
                if len(results) != len(requests):
                    raise RuntimeError("model returned wrong batch length")
                for (_, future), result in zip(requests, results, strict=True):
                    future.set_result(result)
            except Exception as exc:
                for _, future in requests:
                    future.set_exception(exc)

    def close(self):
        with self.condition:
            self.closed = True
            for _, future in self.pending.values():
                future.cancel()
            self.pending.clear()
            self.condition.notify_all()
        self.thread.join(timeout=15)
