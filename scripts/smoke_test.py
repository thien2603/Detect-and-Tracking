import argparse
import json
import logging
from urllib.request import urlopen

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)

def main():
    console_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    for path in ("/health", "/api/v1/cameras", "/api/v1/events?limit=3"):
        with urlopen(args.base.rstrip("/") + path, timeout=15) as response:
            data = json.load(response)
        LOGGER.info("%s %s", path, json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
