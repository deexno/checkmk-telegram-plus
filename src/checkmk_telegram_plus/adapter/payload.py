"""Build and serialize notification payloads from Checkmk environment data."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Mapping

MAX_FIELD_LENGTH = 8192

NOTIFY_FIELDS = (
    "NOTIFY_PARAMETER_1",
    "NOTIFY_HOSTADDRESS",
    "NOTIFY_HOSTNAME",
    "NOTIFY_HOSTGROUPNAMES",
    "NOTIFY_WHAT",
    "NOTIFY_SERVICEDESC",
    "NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE",
    "NOTIFY_SERVICESHORTSTATE",
    "NOTIFY_SERVICEOUTPUT",
    "NOTIFY_PREVIOUSHOSTHARDSHORTSTATE",
    "NOTIFY_HOSTSHORTSTATE",
    "NOTIFY_HOSTOUTPUT",
)


def clean_field(value: object, max_length: int = MAX_FIELD_LENGTH) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > max_length:
        return text[: max_length - 16] + "...[truncated]"
    return text


def collect_notification(env: Mapping[str, str] | None = None) -> dict[str, object]:
    source = os.environ if env is None else env
    notify = {field: clean_field(source.get(field, "")) for field in NOTIFY_FIELDS}
    notify_what = notify.get("NOTIFY_WHAT") or "HOST"
    is_service = str(notify_what).upper() == "SERVICE"

    if is_service:
        description = notify["NOTIFY_SERVICEDESC"]
        from_state = notify["NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE"]
        to_state = notify["NOTIFY_SERVICESHORTSTATE"]
        output = notify["NOTIFY_SERVICEOUTPUT"]
    else:
        description = "HOST STATUS"
        from_state = notify["NOTIFY_PREVIOUSHOSTHARDSHORTSTATE"]
        to_state = notify["NOTIFY_HOSTSHORTSTATE"]
        output = notify["NOTIFY_HOSTOUTPUT"]

    created = datetime.now(timezone.utc).isoformat()
    legacy_event = ";".join(
        [
            notify["NOTIFY_PARAMETER_1"],
            notify["NOTIFY_HOSTADDRESS"],
            notify["NOTIFY_HOSTNAME"],
            notify["NOTIFY_HOSTGROUPNAMES"],
            description,
            from_state,
            to_state,
            output,
        ]
    )

    return {
        "schema": "checkmk-telegram-plus.notification.v1",
        "event_id": str(uuid.uuid4()),
        "created": created,
        "priority": 0,
        "legacy_event": legacy_event,
        "checkmk": notify,
        "service": is_service,
    }


def payload_to_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def payload_from_json(raw: bytes | str) -> dict[str, object]:
    data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    if not isinstance(data, dict):
        raise ValueError("notification payload must be a JSON object")
    if data.get("schema") != "checkmk-telegram-plus.notification.v1":
        raise ValueError("unsupported notification payload schema")
    if not data.get("event_id") or not data.get("legacy_event"):
        raise ValueError("notification payload is missing required fields")
    return data

