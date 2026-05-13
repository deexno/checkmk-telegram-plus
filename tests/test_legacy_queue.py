import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "resources"))

import fqueue  # noqa: E402
from checkmk_telegram_plus.queue.legacy import append_legacy_queue  # noqa: E402


class LegacyQueueTest(unittest.TestCase):
    def test_queue_preserves_payload_for_smart_notifications(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "notifications.queue"
            payload = {
                "schema": "checkmk-telegram-plus.notification.v1",
                "event_id": "evt-smart",
                "created": "2026-05-13T08:00:00+00:00",
                "priority": 0,
                "legacy_event": "notifications_smart;192.0.2.10;host;net;CPU;OK;CRITICAL;bad",
                "checkmk": {"NOTIFY_HOSTNAME": "host", "NOTIFY_WHAT": "SERVICE"},
                "service": True,
            }

            append_legacy_queue(queue_path, payload)
            items = fqueue.Queue(queue_path).get_queue()

            self.assertEqual(items[0]["id"], "evt-smart")
            self.assertEqual(items[0]["payload"]["checkmk"]["NOTIFY_HOSTNAME"], "host")

    def test_queue_reads_existing_four_field_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "notifications.queue"
            queue_path.write_text("event|||id-1|||0|||created\n", encoding="utf-8")

            items = fqueue.Queue(queue_path).get_queue()

            self.assertEqual(items[0]["event"], "event")
            self.assertIsNone(items[0]["payload"])


if __name__ == "__main__":
    unittest.main()
