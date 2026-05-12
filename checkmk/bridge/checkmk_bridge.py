#!/usr/bin/env python3
"""Slim Checkmk bridge for Checkmk Telegram Plus.

The external app must not import Checkmk internals or execute Checkmk commands
directly. This bridge runs as the Checkmk site user, exposes a local Unix socket
and implements a small allowlist of typed operations needed by the app.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import socketserver
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

SITE = "<omd_site>"
SITE_DIR = Path("/omd/sites") / SITE
SOCKET_PATH = "<bridge_socket_path>"
MAX_BODY_SIZE = 1024 * 1024
MAX_FIELD_LENGTH = 512


def add_checkmk_site_python_paths() -> None:
    paths = []
    for base in (SITE_DIR / "lib", SITE_DIR / "local" / "lib"):
        for python_dir in [base / "python3", *base.glob("python3.*")]:
            paths.append(python_dir)
            paths.append(python_dir / "site-packages")
    for path in reversed(paths):
        path_text = str(path)
        if path.exists() and path_text not in sys.path:
            sys.path.insert(0, path_text)


add_checkmk_site_python_paths()

import livestatus  # noqa: E402

livestatus_connection = livestatus.SingleSiteConnection(
    f"unix:{SITE_DIR}/tmp/run/live"
)


def clean_name(value: Any, field: str) -> str:
    text = "" if value is None else str(value)
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > MAX_FIELD_LENGTH:
        raise ValueError(f"{field} is too long")
    if any(char in text for char in ("\x00", "\n", "\r")):
        raise ValueError(f"{field} contains invalid control characters")
    return text


def query_table(query: str) -> list[list[Any]]:
    return [list(row) for row in livestatus_connection.query_table(query)]


def list_hostgroups(params: dict[str, Any]) -> list[str]:
    rows = query_table("GET hostgroups\nColumns: name\n")
    return [str(row[0]) for row in sorted(rows, key=lambda row: row[0])]


def list_hosts(params: dict[str, Any]) -> list[str]:
    hostgroup = clean_name(params.get("hostgroup"), "hostgroup")
    rows = query_table(
        "GET hostsbygroup\n"
        f"Filter: hostgroup_name = {hostgroup}\n"
        "Columns: name"
    )
    return [str(row[0]) for row in sorted(rows, key=lambda row: row[0])]


def list_services(params: dict[str, Any]) -> list[dict[str, Any]]:
    hostname = clean_name(params.get("hostname"), "hostname")
    rows = query_table(
        "GET services\n"
        f"Filter: host_name = {hostname}\n"
        "Columns: description state\n"
    )
    return [
        {"description": str(description), "state": state}
        for description, state in sorted(rows, key=lambda row: row[0])
    ]


def host_status(params: dict[str, Any]) -> dict[str, Any]:
    hostname = clean_name(params.get("hostname"), "hostname")
    rows = query_table(f"GET hosts\nFilter: name = {hostname}\nColumns: state")
    if not rows:
        raise ValueError("host not found")
    return {"state": rows[0][0]}


def service_details(params: dict[str, Any]) -> dict[str, Any]:
    hostname = clean_name(params.get("hostname"), "hostname")
    service = clean_name(params.get("service"), "service")
    rows = query_table(
        "GET services\n"
        f"Filter: host_name = {hostname}\n"
        f"Filter: description = {service}\n"
        "Columns: description state perf_data plugin_output long_plugin_output last_check "
    )
    if not rows:
        raise ValueError("service not found")
    row = rows[0]
    return {
        "description": row[0],
        "state": row[1],
        "perf_data": row[2],
        "plugin_output": row[3],
        "long_plugin_output": row[4],
        "last_check": row[5],
    }


def service_graphs(params: dict[str, Any]) -> list[str]:
    try:
        from cmk.notification_plugins.utils import render_cmk_graphs
    except Exception as exc:
        raise RuntimeError(
            "Checkmk graph rendering is unavailable in this site Python "
            f"environment: {exc}"
        ) from exc

    hostname = clean_name(params.get("hostname"), "hostname")
    service = clean_name(params.get("service"), "service")
    render_config = {
        "HOSTNAME": hostname,
        "SERVICEDESC": service,
        "WHAT": "SERVICE",
        "OMD_SITE": SITE,
        "PARAMETER_GRAPHS_PER_NOTIFICATION": "15",
    }
    return [
        base64.b64encode(graph.data).decode("ascii")
        for graph in list(render_cmk_graphs(render_config))
    ]


def run_cmk_check(params: dict[str, Any]) -> dict[str, Any]:
    hostname = clean_name(params.get("hostname"), "hostname")
    result = subprocess.run(
        [str(SITE_DIR / "bin" / "cmk"), "--check", hostname],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        check=False,
    )
    return {"returncode": result.returncode, "stdout": result.stdout}


def host_problems(params: dict[str, Any]) -> list[dict[str, Any]]:
    hostgroup = clean_name(params.get("hostgroup"), "hostgroup")
    rows = query_table(
        "GET hostsbygroup\n"
        "Filter: state = 1\n"
        "Filter: state = 2\n"
        "Filter: state = 3\n"
        "Or: 3\n"
        f"Filter: hostgroup_name = {hostgroup}\n"
        "Columns: name state"
    )
    return [
        {"hostname": str(host), "state": state}
        for host, state in sorted(rows, key=lambda row: row[1], reverse=True)
    ]


def service_problems(params: dict[str, Any]) -> list[dict[str, Any]]:
    hostgroup = clean_name(params.get("hostgroup"), "hostgroup")
    rows = query_table(
        "GET servicesbyhostgroup\n"
        "Filter: state = 1\n"
        "Filter: state = 2\n"
        "Filter: state = 3\n"
        "Or: 3\n"
        f"Filter: hostgroup_name = {hostgroup}\n"
        "Columns: host_name description state\n"
    )
    return [
        {"hostname": str(host), "description": str(service), "state": state}
        for host, service, state in sorted(rows, key=lambda row: row[2], reverse=True)
    ]


def omd(params: dict[str, Any]) -> dict[str, Any]:
    command = clean_name(params.get("command"), "command")
    if command not in {"status", "start", "stop"}:
        raise ValueError("unsupported omd command")
    result = subprocess.run(
        [str(SITE_DIR / "bin" / "omd"), command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=120,
        check=False,
    )
    return {"returncode": result.returncode, "stdout": result.stdout}


def acknowledge_service_problem(params: dict[str, Any]) -> dict[str, Any]:
    hostname = clean_name(params.get("hostname"), "hostname")
    service = clean_name(params.get("service"), "service")
    username = clean_name(params.get("username"), "username")
    user_id = clean_name(params.get("user_id"), "user_id")
    comment = (
        "ACKNOWLEDGE_SVC_PROBLEM;"
        f"{hostname};"
        f"{service};"
        "2;"
        "0;"
        "0;"
        f"{username};"
        "The problem was acknowledged via the Telegram bot by "
        f"{username} ({user_id})."
    )
    with (SITE_DIR / "tmp" / "run" / "nagios.cmd").open("w", encoding="utf-8") as f:
        f.write(f"[{int(time.time())}] {comment}\n")
    return {"acknowledged": True}


ACTIONS = {
    "list_hostgroups": list_hostgroups,
    "list_hosts": list_hosts,
    "list_services": list_services,
    "host_status": host_status,
    "service_details": service_details,
    "service_graphs": service_graphs,
    "run_cmk_check": run_cmk_check,
    "host_problems": host_problems,
    "service_problems": service_problems,
    "omd": omd,
    "acknowledge_service_problem": acknowledge_service_problem,
}


class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/checkmk":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_SIZE:
                self.send_error(413)
                return
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            action = request.get("action")
            params = request.get("params") or {}
            if action not in ACTIONS:
                raise ValueError("unsupported action")
            result = ACTIONS[action](params)
            self.send_json({"ok": True, "result": result})
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(format % args, file=sys.stderr)


class UnixServer(socketserver.TCPServer):
    address_family = socket.AF_UNIX
    allow_reuse_address = True

    def server_close(self) -> None:
        super().server_close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)


def main() -> int:
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)
    old_umask = os.umask(0o007)
    with UnixServer(SOCKET_PATH, BridgeHandler) as server:
        os.chmod(SOCKET_PATH, 0o660)
        try:
            server.serve_forever()
        finally:
            os.umask(old_umask)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
