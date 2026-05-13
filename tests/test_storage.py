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
            parser.set("telegram_bot", "notifications_smart", "alice (1001),")

            storage = AppStorage(database_path_from_config(parser))
            storage.migrate_from_config(parser)

            self.assertTrue(storage.is_user_authenticated(1001))
            self.assertTrue(storage.is_user_admin(1001))
            self.assertFalse(storage.is_user_admin(1002))
            self.assertEqual(storage.notification_recipients("notifications_loud"), [1002])
            self.assertTrue(storage.notification_enabled(1001, "notifications_silent"))
            self.assertTrue(storage.notification_enabled(1001, "notifications_smart"))
            self.assertEqual(storage.notification_recipients("notifications_smart"), [1001])

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
            storage.record_delivery(
                event_id="evt-1",
                telegram_id=0,
                status="suppressed",
                error="duplicate smart alert",
            )

            notifications = storage.recent_notifications()
            self.assertEqual(notifications[0]["event_id"], "evt-1")
            self.assertEqual(notifications[0]["sent_count"], 1)
            self.assertEqual(notifications[0]["delivery_count"], 2)
            deliveries = storage.notification_deliveries("evt-1")
            self.assertIn("sent", {delivery["status"] for delivery in deliveries})
            self.assertIn("suppressed", {delivery["status"] for delivery in deliveries})
            self.assertEqual(
                storage.notification_event_id_for_delivery(1001, 42),
                "evt-1",
            )

    def test_reads_notification_event_and_targeted_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = AppStorage(Path(tmp) / "state.sqlite3")
            storage.record_notification_event(
                event_id="evt-2",
                notification_type="notifications_loud",
                ip_address="192.0.2.2",
                hostname="host2",
                hostgroup="linux",
                service_description="Interface 1",
                from_state="OK",
                to_state="WARN",
                output="link degraded",
                raw_event="raw",
            )
            storage.add_audit(
                actor_type="telegram",
                actor_id="1001",
                actor_name="alice",
                action="recheck_requested",
                target="evt-2",
                details="host=host2 service=Interface 1",
            )

            self.assertEqual(storage.notification_event("evt-2")["hostname"], "host2")
            self.assertEqual(storage.audit_for_target("evt-2")[0]["actor_name"], "alice")

    def test_smart_notification_history_is_compact(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = AppStorage(Path(tmp) / "state.sqlite3")
            storage.record_notification_event(
                event_id="evt-3",
                notification_type="notifications_smart",
                ip_address="192.0.2.3",
                hostname="switch1",
                hostgroup="network",
                service_description="HOST STATUS",
                from_state="UP",
                to_state="DOWN",
                output="x" * 600,
                raw_event="raw",
            )

            history = storage.smart_notification_history()

            self.assertEqual(history[0]["event_id"], "evt-3")
            self.assertEqual(history[0]["notification_type"], "notifications_smart")
            self.assertTrue(history[0]["output"].endswith("...[truncated]"))

    def test_persists_notification_reminders(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = AppStorage(Path(tmp) / "state.sqlite3")
            reminder_id = storage.create_notification_reminder(
                event_id="evt-4",
                telegram_id=1001,
                hostname="host4",
                service_description="CPU load",
                reminder_label="30 Min.",
                due_at=12345,
                requested_by="alice",
            )

            reminders = storage.pending_notification_reminders()
            self.assertEqual(reminders[0]["id"], reminder_id)
            self.assertEqual(reminders[0]["hostname"], "host4")

            storage.mark_notification_reminder_sent(reminder_id, 99)
            self.assertEqual(storage.pending_notification_reminders(), [])

            failed_id = storage.create_notification_reminder(
                event_id="evt-5",
                telegram_id=1002,
                hostname="host5",
                service_description="Memory",
                reminder_label="60 Min.",
                due_at=12346,
                requested_by="bob",
            )
            storage.mark_notification_reminder_failed(failed_id, "boom")
            self.assertEqual(storage.pending_notification_reminders(), [])


if __name__ == "__main__":
    unittest.main()
