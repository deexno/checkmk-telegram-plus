"""Unix domain socket endpoint for Checkmk notification handoff."""

from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from checkmk_telegram_plus.adapter.payload import payload_from_json
from checkmk_telegram_plus.queue.legacy import (
    append_legacy_queue,
    read_jsonl,
    rewrite_jsonl,
)


class _NotificationHandler(BaseHTTPRequestHandler):
    server: "_NotificationServer"

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path != "/v1/notifications":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > self.server.max_body_size:
                self.send_error(413)
                return
            payload = payload_from_json(self.rfile.read(length))
            appended = append_legacy_queue(self.server.legacy_queue_path, payload)
            self.send_response(202 if appended else 200)
            self.end_headers()
            self.wfile.write(b"OK\n")
        except Exception as exc:  # pragma: no cover - defensive logging path
            self.server.log_error("notification handoff failed: %s", exc)
            self.send_error(400)

    def log_message(self, format: str, *args: Any) -> None:
        if self.server.logger is not None:
            self.server.logger.debug(format, *args)


class _UnixStreamServer(socketserver.TCPServer):
    address_family = getattr(socket, "AF_UNIX", socket.AF_INET)


class _NotificationServer(_UnixStreamServer):
    allow_reuse_address = True

    def __init__(
        self,
        socket_path: str,
        legacy_queue_path: str,
        logger: Any = None,
        max_body_size: int = 1024 * 1024,
    ) -> None:
        self.socket_path = socket_path
        self.legacy_queue_path = legacy_queue_path
        self.logger = logger
        self.max_body_size = max_body_size
        Path(socket_path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        super().__init__(socket_path, _NotificationHandler)
        os.chmod(socket_path, 0o660)

    def server_close(self) -> None:
        super().server_close()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def log_error(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)


class NotificationSocketService:
    def __init__(
        self,
        socket_path: str,
        legacy_queue_path: str,
        fallback_queue_path: str | None = None,
        logger: Any = None,
    ) -> None:
        self.socket_path = socket_path
        self.legacy_queue_path = legacy_queue_path
        self.fallback_queue_path = fallback_queue_path
        self.logger = logger
        self._server: _NotificationServer | None = None
        self._stop = threading.Event()

    def serve_forever(self) -> None:
        self._server = _NotificationServer(
            self.socket_path, self.legacy_queue_path, self.logger
        )
        try:
            self._server.serve_forever(poll_interval=0.5)
        finally:
            self._server.server_close()

    def shutdown(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()

    def drain_fallback_once(self) -> int:
        if not self.fallback_queue_path:
            return 0
        path = Path(self.fallback_queue_path)
        items = read_jsonl(path)
        if not items:
            return 0
        remaining: list[dict[str, object]] = []
        moved = 0
        for item in items:
            try:
                payload_from_json(json.dumps(item, ensure_ascii=False))
                append_legacy_queue(self.legacy_queue_path, item)
                moved += 1
            except Exception:
                remaining.append(item)
        rewrite_jsonl(path, remaining)
        return moved

    def drain_fallback_forever(self, interval: int = 10) -> None:
        while not self._stop.is_set():
            try:
                moved = self.drain_fallback_once()
                if moved and self.logger is not None:
                    self.logger.info("moved %s fallback notifications", moved)
            except Exception as exc:  # pragma: no cover - defensive logging path
                if self.logger is not None:
                    self.logger.warning("fallback drain failed: %s", exc)
            self._stop.wait(interval)
