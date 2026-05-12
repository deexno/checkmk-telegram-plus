"""Unix socket client for the slim Checkmk bridge."""

from __future__ import annotations

import base64
import json
import socket
from typing import Any


class CheckmkBridgeError(RuntimeError):
    pass


class CheckmkBridgeClient:
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def call(self, action: str, **params: Any) -> Any:
        body = json.dumps(
            {"action": action, "params": params},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = (
            b"POST /v1/checkmk HTTP/1.1\r\n"
            b"Host: checkmk-telegram-plus-bridge\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect(self.socket_path)
            client.sendall(request)
            response = b""
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk

        header, _, raw_body = response.partition(b"\r\n\r\n")
        status = header.split(b"\r\n", 1)[0]
        if not status.startswith((b"HTTP/1.0 200", b"HTTP/1.1 200")):
            raise CheckmkBridgeError(status.decode("utf-8", "replace"))
        payload = json.loads(raw_body.decode("utf-8"))
        if not payload.get("ok"):
            raise CheckmkBridgeError(str(payload.get("error", "bridge call failed")))
        return payload.get("result")

    def list_hostgroups(self) -> list[str]:
        return self.call("list_hostgroups")

    def list_hosts(self, hostgroup: str) -> list[str]:
        return self.call("list_hosts", hostgroup=hostgroup)

    def list_services(self, hostname: str) -> list[dict[str, Any]]:
        return self.call("list_services", hostname=hostname)

    def host_status(self, hostname: str) -> int:
        return int(self.call("host_status", hostname=hostname)["state"])

    def service_details(self, hostname: str, service: str) -> dict[str, Any]:
        return self.call("service_details", hostname=hostname, service=service)

    def service_graphs(self, hostname: str, service: str) -> list[bytes]:
        graphs = self.call("service_graphs", hostname=hostname, service=service)
        return [base64.b64decode(graph) for graph in graphs]

    def run_cmk_check(self, hostname: str) -> str:
        return self.call("run_cmk_check", hostname=hostname)["stdout"]

    def host_problems(self, hostgroup: str) -> list[dict[str, Any]]:
        return self.call("host_problems", hostgroup=hostgroup)

    def service_problems(self, hostgroup: str) -> list[dict[str, Any]]:
        return self.call("service_problems", hostgroup=hostgroup)

    def omd(self, command: str) -> str:
        return self.call("omd", command=command)["stdout"]

    def acknowledge_service_problem(
        self,
        *,
        hostname: str,
        service: str,
        username: str,
        user_id: int,
    ) -> None:
        self.call(
            "acknowledge_service_problem",
            hostname=hostname,
            service=service,
            username=username,
            user_id=user_id,
        )
