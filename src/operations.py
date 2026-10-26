"""Bounded, read-only diagnostics for explicitly configured robot targets."""

import fcntl
import ipaddress
import re
import socket
import struct
import subprocess
import time
from pathlib import Path


_ID = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SERVICE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,63}$")


def local_interfaces():
    """IPv4 addresses of this gateway host, without invoking a shell."""
    found = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            try:
                raw = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack("256s", name[:15].encode()))
                address = socket.inet_ntoa(raw[20:24])
            except OSError:
                continue
            if not address.startswith("127."):
                found.append({"name": name, "address": address})
    return found


class OperationsInspector:
    def __init__(self, config, root=None):
        root = Path(root or Path(__file__).resolve().parents[1]).resolve()
        workspace = root.parent
        self.targets = {}
        for item in (config.get("operations") or {}).get("targets", []):
            try:
                identifier = str(item["id"])
                address = ipaddress.ip_address(str(item["ip"]))
                subnet = ipaddress.ip_network(str(item.get("subnet", str(address) + "/24")), strict=False)
                host = ipaddress.ip_address(str(item["oraculum_host"])) if item.get("oraculum_host") else None
                repo = (root / str(item.get("repo", (config.get("fleet") or {}).get("repo", "../spqrbooster2026")))).resolve()
                user = str(item.get("user", "booster"))
                service = str(item.get("service", "maximus"))
                model = str(item.get("model", ""))
                number = item.get("number")
                dual_board = item.get("dual_board")
                if not (_ID.fullmatch(identifier) and address.version == 4 and address.is_private
                        and not address.is_loopback and not address.is_link_local
                        and subnet.version == 4 and address in subnet and subnet.prefixlen >= 8
                        and (host is None or (host.version == 4 and host in subnet and host != address))
                        and (repo == workspace or workspace in repo.parents)
                        and _USER.fullmatch(user) and _SERVICE.fullmatch(service)
                        and model in ("", "t1", "t2", "k1")
                        and (number is None or (type(number) is int and 1 <= number <= 99))
                        and (dual_board is None or type(dual_board) is bool)):
                    raise ValueError("invalid target")
                if identifier in self.targets:
                    raise ValueError("duplicate target")
                self.targets[identifier] = {
                    "id": identifier, "name": str(item.get("name", identifier))[:48],
                    "ip": str(address), "subnet": str(subnet), "user": user, "service": service,
                    "model": model, "repo": str(repo),
                    "oraculum_host": str(host) if host else None,
                    "number": number, "dual_board": dual_board,
                }
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid operations target in config.yaml") from exc

    def inventory(self):
        interfaces = local_interfaces()
        targets = []
        for item in self.targets.values():
            subnet = ipaddress.ip_network(item["subnet"])
            gateway = next((i["address"] for i in interfaces if ipaddress.ip_address(i["address"]) in subnet), None)
            configured = item["oraculum_host"] or gateway
            targets.append({**item, "gateway_address": configured, "gateway_interface": gateway,
                            "gateway_connected": bool(gateway and gateway == configured)})
        return {"targets": targets, "interfaces": interfaces,
                "observed_at": round(time.time(), 3)}

    def probe(self, identifier, *, connect=socket.create_connection, run=subprocess.run):
        """Only a configured target. No remote mutation or caller-supplied command."""
        target = self.targets.get(identifier)
        if target is None:
            raise KeyError(identifier)
        result = {"target": identifier, "ip": target["ip"], "observed_at": round(time.time(), 3),
                  "ssh_port": False, "ssh": "not attempted", "service": "unknown",
                  "version": "unknown", "joysticks": "unknown", "logs": []}
        try:
            with connect((target["ip"], 22), timeout=1.5):
                result["ssh_port"] = True
        except OSError as exc:
            result["ssh"] = "unreachable: " + str(exc)[:140]
            return result

        # Fixed script, fixed output markers and an allowlisted service. BatchMode never prompts for a password.
        service = target["service"]
        script = ("printf 'ORC_SERVICE='; systemctl is-active " + service + " 2>/dev/null || true\n"
                  "printf 'ORC_VERSION='; head -c 160 /home/booster/spqr/maximus/build/aarch64/src/app/config/version.txt 2>/dev/null; printf '\\n'\n"
                  "printf 'ORC_JOYSTICKS='; ls /dev/input/js* 2>/dev/null | tr '\\n' ','; printf '\\n'\n"
                  "printf 'ORC_LOGS_BEGIN\\n'; journalctl -u " + service + " -n 30 --no-pager --output=short-iso 2>/dev/null || true\n")
        args = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "NumberOfPasswordPrompts=0",
                "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=2",
                target["user"] + "@" + target["ip"], "sh", "-s"]
        try:
            completed = run(args, input=script, text=True, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result["ssh"] = "probe failed: " + str(exc)[:140]
            return result
        if completed.returncode:
            result["ssh"] = "unavailable: " + completed.stderr.strip()[:180]
            return result
        result["ssh"] = "connected"
        header, _, logs = completed.stdout[:16000].partition("ORC_LOGS_BEGIN\n")
        for line in header.splitlines():
            if line.startswith("ORC_SERVICE="):
                result["service"] = line.removeprefix("ORC_SERVICE=").strip() or "unknown"
            elif line.startswith("ORC_VERSION="):
                result["version"] = line.removeprefix("ORC_VERSION=").strip() or "unknown"
            elif line.startswith("ORC_JOYSTICKS="):
                result["joysticks"] = line.removeprefix("ORC_JOYSTICKS=").strip() or "none"
        result["logs"] = logs.splitlines()[-30:]
        return result
