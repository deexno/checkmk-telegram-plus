"""SQLite persistence for runtime state.

The configuration file should describe how the app connects to its environment.
Mutable application state such as authenticated Telegram users, notification
subscriptions and delivery logs belongs in the state directory instead.
"""

from __future__ import annotations

import configparser
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


USER_RE = re.compile(r"(?P<name>.*?)\s*\((?P<id>\d+)\)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def database_path_from_config(config: configparser.RawConfigParser) -> str:
    env_path = os.environ.get("CHECKMK_TELEGRAM_PLUS_DB")
    if env_path:
        return env_path
    state_dir = ""
    if config.has_section("paths"):
        state_dir = config.get("paths", "state_dir", fallback="")
    if not state_dir or state_dir.startswith("<"):
        site = config.get("check_mk", "site", fallback="default")
        state_dir = str(Path("/var/lib/checkmk-telegram-plus") / site)
    return str(Path(state_dir) / "telegram-plus.sqlite3")


class AppStorage:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    first_name TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    notify_loud INTEGER NOT NULL DEFAULT 0,
                    notify_silent INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    authenticated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_events (
                    event_id TEXT PRIMARY KEY,
                    notification_type TEXT NOT NULL,
                    ip_address TEXT NOT NULL DEFAULT '',
                    hostname TEXT NOT NULL DEFAULT '',
                    hostgroup TEXT NOT NULL DEFAULT '',
                    service_description TEXT NOT NULL DEFAULT '',
                    from_state TEXT NOT NULL DEFAULT '',
                    to_state TEXT NOT NULL DEFAULT '',
                    output TEXT NOT NULL DEFAULT '',
                    raw_event TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    telegram_message_id INTEGER,
                    error TEXT NOT NULL DEFAULT '',
                    sent_at TEXT NOT NULL,
                    FOREIGN KEY(event_id) REFERENCES notification_events(event_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_notification_events_created
                    ON notification_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_notification_deliveries_event
                    ON notification_deliveries(event_id);

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT '',
                    actor_name TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    details TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def migrate_from_config(self, config: configparser.RawConfigParser) -> None:
        if not config.has_section("telegram_bot"):
            return
        section = config["telegram_bot"]
        admin_ids = self._ids_from_user_list(section.get("admin_users", ""))
        loud_ids = self._ids_from_user_list(section.get("notifications_loud", ""))
        silent_ids = self._ids_from_user_list(section.get("notifications_silent", ""))

        for user in self._users_from_config(section.get("allowed_users", "")):
            telegram_id = user["telegram_id"]
            self.upsert_user(
                telegram_id=telegram_id,
                username=user["username"],
                is_admin=telegram_id in admin_ids,
                notify_loud=telegram_id in loud_ids,
                notify_silent=telegram_id in silent_ids,
            )

    def upsert_user(
        self,
        *,
        telegram_id: int,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
        is_admin: bool | None = None,
        notify_loud: bool | None = None,
        notify_silent: bool | None = None,
        active: bool = True,
    ) -> None:
        now = utc_now()
        with self.connect() as db:
            current = db.execute(
                "SELECT * FROM app_users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            if current is None:
                db.execute(
                    """
                    INSERT INTO app_users (
                        telegram_id, username, first_name, last_name, is_admin,
                        notify_loud, notify_silent, active, authenticated_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        telegram_id,
                        username or "",
                        first_name or "",
                        last_name or "",
                        int(bool(is_admin)),
                        int(bool(notify_loud)),
                        int(bool(notify_silent)),
                        int(active),
                        now,
                        now,
                    ),
                )
                return
            db.execute(
                """
                UPDATE app_users
                SET username = COALESCE(NULLIF(?, ''), username),
                    first_name = COALESCE(NULLIF(?, ''), first_name),
                    last_name = COALESCE(NULLIF(?, ''), last_name),
                    is_admin = COALESCE(?, is_admin),
                    notify_loud = COALESCE(?, notify_loud),
                    notify_silent = COALESCE(?, notify_silent),
                    active = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (
                    username or "",
                    first_name or "",
                    last_name or "",
                    None if is_admin is None else int(is_admin),
                    None if notify_loud is None else int(notify_loud),
                    None if notify_silent is None else int(notify_silent),
                    int(active),
                    now,
                    telegram_id,
                ),
            )

    def is_user_authenticated(self, telegram_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT active FROM app_users WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
            return bool(row and row["active"])

    def is_user_admin(self, telegram_id: int) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT is_admin, active FROM app_users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            return bool(row and row["active"] and row["is_admin"])

    def set_notification_preference(
        self, telegram_id: int, notification_type: str, enabled: bool
    ) -> None:
        if notification_type not in {"notifications_loud", "notifications_silent"}:
            raise ValueError("unsupported notification type")
        column = "notify_loud" if notification_type == "notifications_loud" else "notify_silent"
        with self.connect() as db:
            db.execute(
                f"UPDATE app_users SET {column} = ?, updated_at = ? WHERE telegram_id = ?",
                (int(enabled), utc_now(), telegram_id),
            )

    def notification_enabled(self, telegram_id: int, notification_type: str) -> bool:
        column = "notify_loud" if notification_type == "notifications_loud" else "notify_silent"
        with self.connect() as db:
            row = db.execute(
                f"SELECT {column}, active FROM app_users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            return bool(row and row["active"] and row[column])

    def notification_recipients(self, notification_type: str) -> list[int]:
        column = "notify_loud" if notification_type == "notifications_loud" else "notify_silent"
        with self.connect() as db:
            rows = db.execute(
                f"SELECT telegram_id FROM app_users WHERE active = 1 AND {column} = 1"
            ).fetchall()
            return [int(row["telegram_id"]) for row in rows]

    def all_active_users(self) -> list[int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT telegram_id FROM app_users WHERE active = 1"
            ).fetchall()
            return [int(row["telegram_id"]) for row in rows]

    def list_users(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM app_users
                ORDER BY active DESC, is_admin DESC, username COLLATE NOCASE, telegram_id
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_user(self, telegram_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE app_users SET active = 0, updated_at = ? WHERE telegram_id = ?", (utc_now(), telegram_id))

    def record_notification_event(
        self,
        *,
        event_id: str,
        notification_type: str,
        ip_address: str,
        hostname: str,
        hostgroup: str,
        service_description: str,
        from_state: str,
        to_state: str,
        output: str,
        raw_event: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO notification_events (
                    event_id, notification_type, ip_address, hostname, hostgroup,
                    service_description, from_state, to_state, output, raw_event,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    notification_type,
                    ip_address,
                    hostname,
                    hostgroup,
                    service_description,
                    from_state,
                    to_state,
                    output,
                    raw_event,
                    utc_now(),
                ),
            )

    def record_delivery(
        self,
        *,
        event_id: str,
        telegram_id: int,
        status: str,
        telegram_message_id: int | None = None,
        error: str = "",
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO notification_deliveries (
                    event_id, telegram_id, status, telegram_message_id, error, sent_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_id, telegram_id, status, telegram_message_id, error, utc_now()),
            )

    def recent_notifications(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT e.*,
                    COUNT(d.id) AS delivery_count,
                    SUM(CASE WHEN d.status = 'sent' THEN 1 ELSE 0 END) AS sent_count,
                    SUM(CASE WHEN d.status != 'sent' THEN 1 ELSE 0 END) AS failed_count
                FROM notification_events e
                LEFT JOIN notification_deliveries d ON d.event_id = e.event_id
                GROUP BY e.event_id
                ORDER BY e.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def notification_deliveries(self, event_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT d.*, u.username
                FROM notification_deliveries d
                LEFT JOIN app_users u ON u.telegram_id = d.telegram_id
                WHERE d.event_id = ?
                ORDER BY d.sent_at DESC
                """,
                (event_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def add_audit(
        self,
        *,
        actor_type: str,
        actor_id: str = "",
        actor_name: str = "",
        action: str,
        target: str = "",
        details: str = "",
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO audit_log (
                    actor_type, actor_id, actor_name, action, target, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (actor_type, actor_id, actor_name, action, target, details, utc_now()),
            )

    def recent_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _ids_from_user_list(value: str) -> set[int]:
        ids: set[int] = set()
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            match = USER_RE.search(item)
            raw_id = match.group("id") if match else item
            if raw_id.isdigit():
                ids.add(int(raw_id))
        return ids

    @staticmethod
    def _users_from_config(value: str) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            match = USER_RE.search(item)
            if match:
                users.append(
                    {
                        "telegram_id": int(match.group("id")),
                        "username": match.group("name").strip(),
                    }
                )
            elif item.isdigit():
                users.append({"telegram_id": int(item), "username": ""})
        return users
