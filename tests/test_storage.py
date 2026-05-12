import configparser
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from checkmk_telegram_plus.storage import AppStorage, database_path_from_config  # noqa: E402


class StorageTest(unittest.TestCase):
    def test_migrates_users_and_notification_preferences_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            parser = configparser.RawConfigParser()
            parser.add_section("check_mk")
            parser.set("check_mk", "site", "mysite")
            parser.add_section("paths")
            parser.set("paths", "state_dir", tmp)
            parser.add_section("telegram_bot")
            parser.set("telegram_bot", "allowed_users", "alice (1001),1002,")
            parser.set("telegram_bot", "admin_users", "alice (1001),")
            parser.set("telegram_bot", "notifications_loud", "1002,")
            parser.set("telegram_bot", "notifications_silent", "alice (1001),")

            storage = AppStorage(database_path_from_config(parser))
            storage.migrate_from_config(parser)

            self.assertTrue(storage.is_user_authenticated(1001))
            self.assertTrue(storage.is_user_admin(1001))
            self.assertFalse(storage.is_user_admin(1002))
            self.assertEqual(storage.notification_recipients("notifications_loud"), [1002])
            self.assertTrue(storage.notification_enabled(1001, "notifications_silent"))

    def test_records_notification_and_deliveries(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = AppStorage(Path(tmp) / "state.sqlite3")
            storage.record_notification_event(
                event_id="evt-1",
                notification_type="notifications_loud",
                ip_address="192.0.2.1",
                hostname="host1",
                hostgroup="linux",
                service_description="CPU load",
                from_state="OK",
                to_state="CRIT",
                output="too high",
                raw_event="raw",
            )
            storage.record_delivery(
                event_id="evt-1",
                telegram_id=1001,
                status="sent",
                telegram_message_id=42,
            )

            notifications = storage.recent_notifications()
            self.assertEqual(notifications[0]["event_id"], "evt-1")
            self.assertEqual(notifications[0]["sent_count"], 1)
            self.assertEqual(
                storage.notification_deliveries("evt-1")[0]["telegram_message_id"],
                42,
            )


if __name__ == "__main__":
    unittest.main()
