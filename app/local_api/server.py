"""Threaded HTTP front-end for the local API.

Wraps the pure :class:`ApiRouter` in a stdlib ``ThreadingHTTPServer`` running on
a background thread. Binds to 127.0.0.1 by default; the caller may pass a
specific LAN address for the opt-in, explicitly-dangerous LAN mode. No third
party dependencies — just the standard library.
"""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from app.local_api.router import MAX_BODY_BYTES, ApiRouter
from app.local_api.sse import SseBroker

DEFAULT_PORT = 7345
LOOPBACK = "127.0.0.1"
_SSE_HEARTBEAT_SECONDS = 15.0


class ApiServer:
    def __init__(
        self,
        router: ApiRouter,
        *,
        host: str = LOOPBACK,
        port: int = DEFAULT_PORT,
        broker: SseBroker | None = None,
    ) -> None:
        self._router = router
        self._broker = broker
        self._host = host or LOOPBACK
        self._port = int(port)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self._httpd is not None:
            return
        self._httpd = ThreadingHTTPServer(
            (self._host, self._port), _make_handler(self._router, self._broker)
        )
        # If the caller asked for an ephemeral port (0), record the real one.
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="lumable-api", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=2.0)


def _make_handler(router: ApiRouter, broker: SseBroker | None) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        # Keep the console quiet — the app has its own logging.
        def log_message(self, *_args: Any) -> None:
            return

        def _path(self) -> str:
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            return path.rstrip("/") or "/"

        def _sse_frame(self, state: dict[str, Any]) -> None:
            self.wfile.write(f"data: {json.dumps(state)}\n\n".encode())
            self.wfile.flush()

        def _json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _stream_events(self) -> None:
            if not router.authorize(dict(self.headers.items())):
                self._json(401, {"error": "unauthorized"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            subscriber = broker.subscribe()
            try:
                self._sse_frame(broker.latest())
                while True:
                    try:
                        state = subscriber.get(timeout=_SSE_HEARTBEAT_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    self._sse_frame(state)
            except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
                pass  # client went away
            finally:
                broker.unsubscribe(subscriber)

        def _dispatch(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            # Never read more than the cap; the router turns oversize into 413.
            body = self.rfile.read(min(max(length, 0), MAX_BODY_BYTES + 1)) if length > 0 else b""
            headers = dict(self.headers.items())
            response = router.handle(method, self.path, headers, body)
            payload = json.dumps(response.body).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if broker is not None and self._path() == "/events":
                self._stream_events()
                return
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

    return _Handler
