import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from checkmk_telegram_plus.adapter.payload import collect_notification  # noqa: E402
from checkmk_telegram_plus.api.notification_socket import (  # noqa: E402
    NotificationSocketService,
)
from checkmk_telegram_plus.queue.legacy import read_jsonl  # noqa: E402


def post_unix_json(socket_path: str, payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = (
        b"POST /v1/notifications HTTP/1.1\r\n"
        b"Host: local\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + body
    )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(socket_path)
        client.sendall(request)
        return client.recv(256)


class NotificationSocketTest(unittest.TestCase):
    def test_socket_appends_legacy_queue_and_deduplicates_event_id(self):
        if not hasattr(socket, "AF_UNIX"):
            self.skipTest("AF_UNIX is unavailable on this platform")

        with tempfile.TemporaryDirectory() as tmp:
            socket_path = os.path.join(tmp, "notify.sock")
            queue_path = os.path.join(tmp, "notifications.queue")
            service = NotificationSocketService(socket_path, queue_path)
            thread = threading.Thread(target=service.serve_forever, daemon=True)
            thread.start()
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.02)

            payload = collect_notification(
                {
                    "NOTIFY_PARAMETER_1": "notifications_loud",
                    "NOTIFY_WHAT": "HOST",
                    "NOTIFY_HOSTNAME": "web01",
                }
            )
            self.assertIn(b" 202 ", post_unix_json(socket_path, payload))
            self.assertIn(b" 200 ", post_unix_json(socket_path, payload))

            with open(queue_path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
            self.assertEqual(len(lines), 1)
            self.assertIn(str(payload["event_id"]), lines[0])
            service.shutdown()

    def test_drain_fallback_moves_jsonl_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = os.path.join(tmp, "notifications.queue")
            fallback_path = os.path.join(tmp, "fallback.jsonl")
            payload = collect_notification(
                {"NOTIFY_PARAMETER_1": "notifications_silent", "NOTIFY_WHAT": "HOST"}
            )
            with open(fallback_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

            service = NotificationSocketService(
                os.path.join(tmp, "unused.sock"), queue_path, fallback_path
            )
            self.assertEqual(service.drain_fallback_once(), 1)
            self.assertEqual(read_jsonl(fallback_path), [])
            with open(queue_path, "r", encoding="utf-8") as handle:
                self.assertIn(str(payload["event_id"]), handle.read())


if __name__ == "__main__":
    unittest.main()

