"""Compatibility helpers for the existing delimiter based queue format."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping


def legacy_queue_line(payload: Mapping[str, object]) -> str:
    event = str(payload["legacy_event"]).replace("\n", "\\n")
    event_id = str(payload["event_id"])
    priority = str(payload.get("priority", 0))
    created = str(payload.get("created", ""))
    return f"{event}|||{event_id}|||{priority}|||{created}\n"


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("|||")
            if len(parts) >= 2:
                ids.add(parts[1])
    return ids


def append_legacy_queue(path: str | os.PathLike[str], payload: Mapping[str, object]) -> bool:
    queue_path = Path(path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    event_id = str(payload["event_id"])
    if event_id in _existing_ids(queue_path):
        return False
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(queue_path, flags, 0o600)
    try:
        os.write(fd, legacy_queue_line(payload).encode("utf-8"))
    finally:
        os.close(fd)
    return True


def read_jsonl(path: str | os.PathLike[str]) -> list[dict[str, object]]:
    queue_path = Path(path)
    if not queue_path.exists():
        return []
    items: list[dict[str, object]] = []
    with queue_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                item = json.loads(line)
                if isinstance(item, dict):
                    items.append(item)
    return items


def rewrite_jsonl(path: str | os.PathLike[str], items: Iterable[Mapping[str, object]]) -> None:
    queue_path = Path(path)
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    if queue_path.exists():
        with queue_path.open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        os.chmod(queue_path, 0o660)
        return

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{queue_path.name}.", dir=str(queue_path.parent), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
        os.replace(tmp_name, queue_path)
        os.chmod(queue_path, 0o660)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
