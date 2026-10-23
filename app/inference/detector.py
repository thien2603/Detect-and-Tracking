import logging
import time
from threading import Lock

from app.config.schemas import ModelConfig
from app.inference.types import Detection

LOGGER = logging.getLogger(__name__)


class YOLODetector:
    """One model, preloaded at service startup and serialized by the scheduler."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self._model = None
        self._classes = None
        self._precision = {}
        self.last_profile_ms = {}
        self._cuda_stream = None
        self._lock = Lock()

    def load(self):
        with self._lock:
            if self._model is not None:
                return
            import torch
            from ultralytics import YOLO
            from ultralytics.cfg import DEFAULT_CFG_DICT
            from ultralytics.utils.torch_utils import select_device

            torch.set_num_threads(self.config.torch_threads)
            model = YOLO(self.config.weights)
            names = {name.lower(): key for key, name in model.names.items()}
            classes = []
            for value in self.config.classes:
                if isinstance(value, int):
                    if value not in model.names:
                        raise ValueError(f"Unknown class ID: {value}")
                    classes.append(value)
                else:
                    if value.lower() not in names:
                        raise ValueError(f"Unknown model class: {value}")
                    classes.append(names[value.lower()])
            if not classes:
                raise ValueError("Specify at least one model class")
            device = select_device(self.config.device, verbose=False)
            model.to(device)
            if self.config.cuda_streams and device.type == "cuda":
                self._cuda_stream = torch.cuda.Stream(device=device)
                self._cuda_stream.wait_stream(torch.cuda.current_stream(device))
            self._classes = sorted(set(classes))
            if self.config.half and device.type == "cuda":
                # New releases renamed half to quantize; avoid per-batch warning spam.
                self._precision = ({"quantize": 16} if "quantize" in DEFAULT_CFG_DICT
                                   else {"half": True})
            self._model = model

    def detect_batch(self, frames):
        if not frames:
            return []
        self.load()
        if self._cuda_stream is not None:
            import torch

            with torch.cuda.stream(self._cuda_stream):
                return self._predict_and_collect(frames)
        return self._predict_and_collect(frames)

    def _predict_and_collect(self, frames):
        results = self._model.predict(
            source=frames,
            conf=self.config.confidence,
            imgsz=self.config.imgsz,
            rect=self.config.rect,
            classes=self._classes,
            device=self.config.device,
            **self._precision,
            verbose=False,
        )
        batches = []
        if results:
            self.last_profile_ms = {key: round(sum((getattr(r, "speed", None) or {}).get(key, 0)
                                                   for r in results), 2)
                                    for key in ("preprocess", "inference", "postprocess")}
        for result in results:
            detections = []
            if result.boxes is not None:
                # One transfer per image, not several GPU synchronizations per box.
                # Both normal (6 columns) and tracked (7 columns) boxes end in conf/cls.
                for row in result.boxes.data.cpu().tolist():
                    class_id = int(row[-1])
                    detections.append(
                        Detection(
                            tuple(float(x) for x in row[:4]),
                            float(row[-2]),
                            class_id,
                            str(result.names[class_id]),
                        )
                    )
            batches.append(detections)
        return batches

    def warmup(self, batch_size):
        """Initialize CUDA kernels before camera render threads contend for CPU/RAM."""
        import numpy as np

        image = np.zeros((self.config.imgsz, self.config.imgsz, 3), dtype=np.uint8)
        for size in range(1, batch_size + 1):
            began = time.perf_counter()
            LOGGER.info("Model warmup batch=%d/%d", size, batch_size)
            self.detect_batch([image] * size)
            LOGGER.info("Model warmup batch=%d ready in %.1f ms", size,
                        (time.perf_counter() - began) * 1000)

    def clone(self):
        """Independent weights/predictor; Python/CUDA libraries remain in one process."""
        return YOLODetector(self.config.model_copy(deep=True))

    def clone_factory(self):
        """Do not keep a disabled prototype model alive through a bound factory method."""
        config = self.config.model_copy(deep=True)
        return lambda: YOLODetector(config.model_copy(deep=True))
