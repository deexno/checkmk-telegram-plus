import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from checkmk_telegram_plus.adapter.payload import (  # noqa: E402
    collect_notification,
    payload_from_json,
    payload_to_json,
)


class AdapterPayloadTest(unittest.TestCase):
    def test_collects_service_notification_as_legacy_event(self):
        payload = collect_notification(
            {
                "NOTIFY_PARAMETER_1": "notifications_loud",
                "NOTIFY_HOSTADDRESS": "192.0.2.10",
                "NOTIFY_HOSTNAME": "db01",
                "NOTIFY_HOSTGROUPNAMES": "databases",
                "NOTIFY_WHAT": "SERVICE",
                "NOTIFY_SERVICEDESC": "Disk /var",
                "NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE": "OK",
                "NOTIFY_SERVICESHORTSTATE": "CRIT",
                "NOTIFY_SERVICEOUTPUT": "disk full",
            }
        )

        self.assertEqual(payload["schema"], "checkmk-telegram-plus.notification.v1")
        self.assertTrue(payload["service"])
        self.assertEqual(
            payload["legacy_event"],
            "notifications_loud;192.0.2.10;db01;databases;Disk /var;OK;CRIT;disk full",
        )

    def test_collects_host_notification_as_legacy_event(self):
        payload = collect_notification(
            {
                "NOTIFY_PARAMETER_1": "notifications_silent",
                "NOTIFY_HOSTADDRESS": "192.0.2.11",
                "NOTIFY_HOSTNAME": "web01",
                "NOTIFY_HOSTGROUPNAMES": "web",
                "NOTIFY_WHAT": "HOST",
                "NOTIFY_PREVIOUSHOSTHARDSHORTSTATE": "UP",
                "NOTIFY_HOSTSHORTSTATE": "DOWN",
                "NOTIFY_HOSTOUTPUT": "packet loss",
            }
        )

        self.assertFalse(payload["service"])
        self.assertEqual(
            payload["legacy_event"],
            "notifications_silent;192.0.2.11;web01;web;HOST STATUS;UP;DOWN;packet loss",
        )

    def test_payload_round_trip_validates_schema(self):
        payload = collect_notification({"NOTIFY_WHAT": "HOST"})
        decoded = payload_from_json(payload_to_json(payload))
        self.assertEqual(decoded["event_id"], payload["event_id"])

        invalid = json.dumps({"schema": "bad"}).encode()
        with self.assertRaises(ValueError):
            payload_from_json(invalid)


if __name__ == "__main__":
    unittest.main()

