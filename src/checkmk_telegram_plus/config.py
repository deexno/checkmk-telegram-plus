"""Configuration migration helpers."""

from __future__ import annotations

import configparser
import shutil
from datetime import datetime
from pathlib import Path


def backup_file(path: str | Path) -> Path | None:
    source = Path(path)
    if not source.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    target = source.with_name(f"{source.name}.bak.{timestamp}")
    shutil.copy2(source, target)
    return target


def ensure_external_paths(
    config_path: str | Path,
    *,
    site: str,
    state_dir: str,
    log_dir: str,
    run_dir: str,
    socket_path: str,
    bridge_socket_path: str,
    fallback_queue_path: str,
) -> None:
    parser = configparser.RawConfigParser()
    parser.read(config_path)
    if not parser.has_section("check_mk"):
        parser.add_section("check_mk")
    parser.set("check_mk", "site", site)
    if not parser.has_section("paths"):
        parser.add_section("paths")
    parser.set("paths", "state_dir", state_dir)
    parser.set("paths", "log_dir", log_dir)
    parser.set("paths", "run_dir", run_dir)
    parser.set("paths", "socket_path", socket_path)
    parser.set("paths", "bridge_socket", bridge_socket_path)
    parser.set("paths", "notification_queue", f"{state_dir}/notifications.queue")
    parser.set("paths", "fallback_queue", fallback_queue_path)
    with Path(config_path).open("w", encoding="utf-8") as handle:
        parser.write(handle)
