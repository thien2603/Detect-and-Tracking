"""Sample API metrics; this is not a ground-truth accuracy or end-to-end latency test."""

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--output", default="docs/benchmark-results/api-metrics.json")
    args = parser.parse_args()
    console_logging()
    if args.seconds <= 0 or args.interval <= 0:
        parser.error("seconds and interval must be positive")
    deadline = time.monotonic() + args.seconds
    samples = []
    while time.monotonic() < deadline:
        with urlopen(args.base.rstrip("/") + "/api/v1/cameras", timeout=10) as response:
            cameras = json.load(response)
        samples.append({"time": datetime.now(timezone.utc).isoformat(), "cameras": cameras})
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"samples": samples, "note": "Internal metrics only"}, indent=2))
    LOGGER.info("Metrics saved to %s", output)


if __name__ == "__main__":
    main()
