"""Run the API with Ctrl+C and an optional task-owned graceful-stop file."""

import argparse
import logging
from pathlib import Path
from threading import Event, Thread

import uvicorn

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)


def main():
    console_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port,
                                          log_level="info", loop="asyncio"))
    done = Event()

    def watch():
        while not done.wait(0.2):
            if args.stop_file and args.stop_file.exists():
                server.should_exit = True
                return

    watcher = Thread(target=watch, name="graceful-stop", daemon=True)
    watcher.start()
    try:
        server.run()
    except KeyboardInterrupt:
        # Uvicorn re-raises SIGINT after its lifespan shutdown has returned.
        # Treat a normal terminal interrupt as an expected exit, not an API crash.
        LOGGER.info("Ctrl+C returned control to the API runner")
    finally:
        done.set()
        watcher.join(timeout=2)
        LOGGER.info("API stopped cleanly")


if __name__ == "__main__":
    main()
