"""Read-only local camera viewer for an already running analytics API."""

import argparse
import contextlib
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, build_opener

LOGGER = logging.getLogger(__name__)
PAGE = Path(__file__).with_name("camera_viewer.html")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    parser.add_argument("--port", type=int, default=18001)
    args = parser.parse_args()
    parsed = urlsplit(args.api)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("--api must point to a local HTTP service")
    opener = build_opener(ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                self.respond(200, "text/html; charset=utf-8", PAGE.read_bytes())
                return
            if path == "/cameras":
                upstream = "/api/v1/cameras"
                kind = "application/json"
            elif re.fullmatch(r"/frame/[A-Za-z0-9_-]+", path):
                identifier = path.rsplit("/", 1)[-1]
                upstream = f"/api/v1/cameras/{quote(identifier)}/frame.jpg"
                kind = "image/jpeg"
            else:
                self.respond(404, "text/plain; charset=utf-8", b"Not found")
                return
            try:
                with opener.open(args.api.rstrip("/") + upstream, timeout=8) as response:
                    self.respond(200, kind, response.read())
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self.respond(503, "application/json", body)

        def log_message(self, fmt, *values):
            LOGGER.debug(fmt, *values)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    LOGGER.info("Camera viewer: http://127.0.0.1:%d (API %s)", args.port, args.api)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Camera viewer stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
