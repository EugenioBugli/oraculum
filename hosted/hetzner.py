#!/usr/bin/env python3
"""Hosted oraculum sessions on Hetzner Cloud: pay only while a session runs.

Hetzner bills a server for every hour it EXISTS (each started hour, 1 h minimum), powered off or not; only deleting it
stops the bill. So a session is: create a server from the golden snapshot -> run -> delete. Between sessions only the
snapshot is billed (EUR 0.0143/GB/month, hetzner.com 2026-10-20). Every server this script creates carries the label
oraculum=session; `delete` and `reap` touch only those. `reap` is the hard stop: the controller runs it on a timer.

Token: an API token (read/write) of the Hetzner project, in ~/.config/hcloud/oraculum.token (mode 600) or $HCLOUD_TOKEN.
This script never prints it. Store it without showing it on screen:
    read -rs T && umask 077 && mkdir -p ~/.config/hcloud && printf '%s' "$T" > ~/.config/hcloud/oraculum.token

    python3 hosted/hetzner.py prices [--location nbg1]                     # live prices from the API (read only)
    python3 hosted/hetzner.py list                                          # session servers, age, cost so far
    python3 hosted/hetzner.py images                                        # golden snapshots
    python3 hosted/hetzner.py firewall                                      # once: inbound SSH only (free)
    python3 hosted/hetzner.py create NAME [--type ccx33] [--image ID|ubuntu-24.04] [--location nbg1]
                                     [--user-data cloud-init.yaml] [--yes]  # dry run (prints the price) without --yes
    python3 hosted/hetzner.py delete NAME
    python3 hosted/hetzner.py snapshot NAME "description"                   # golden image from a built server
    python3 hosted/hetzner.py reap --max-minutes 90                         # delete session servers older than that
    python3 hosted/hetzner.py sshkey-add NAME ~/.ssh/id_ed25519.pub
"""

import json
import math
import os
import pathlib
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.hetzner.cloud/v1"
TOKEN_FILE = pathlib.Path.home() / ".config" / "hcloud" / "oraculum.token"
SESSION = {"oraculum": "session"}
GOLDEN = {"oraculum": "golden"}
# Inbound SSH only. A Hetzner Cloud Firewall filters outside the server, so Docker's own iptables rules cannot open
# anything around it: the plain-HTTP gateway (8080) and noVNC (6080) are reached through an SSH tunnel.
FIREWALL = "oraculum-ssh-only"
SNAPSHOT_EUR_GB_MONTH = 0.0143


def token() -> str:
    t = os.environ.get("HCLOUD_TOKEN", "").strip()
    if not t and TOKEN_FILE.exists():
        if TOKEN_FILE.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            sys.exit(f"{TOKEN_FILE} is readable by other users: run chmod 600 on it")
        t = TOKEN_FILE.read_text().strip()
    if not t:
        sys.exit("no Hetzner API token. Store it without showing it:\n"
                 "  read -rs T && umask 077 && mkdir -p ~/.config/hcloud && printf '%s' \"$T\" > " + str(TOKEN_FILE))
    return t


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:  # the message names the call and Hetzner's error, never the token
        try:
            err = json.loads(e.read()).get("error", {})
        except ValueError:
            err = {}
        sys.exit(f"Hetzner API {method} {path.split('?')[0]}: HTTP {e.code} {err.get('code', '')}: {err.get('message', '')}")


def wait(action: dict, what: str, timeout_s: int = 900) -> None:
    t0 = time.time()
    while action["status"] == "running":
        if time.time() - t0 > timeout_s:
            sys.exit(f"{what}: still running after {timeout_s} s (action {action['id']})")
        time.sleep(3)
        action = call("GET", f"/actions/{action['id']}")["action"]
    if action["status"] != "success":
        sys.exit(f"{what}: {action['status']} {action.get('error')}")


def price(server_type: dict, location: str) -> tuple:
    """(net, gross) EUR per hour of a server type in a location; (None, None) where it is not offered."""
    for p in server_type.get("prices", []):
        if p["location"] == location:
            return float(p["price_hourly"]["net"]), float(p["price_hourly"]["gross"])
    return None, None


def billed_hours(created_iso: str, now: datetime | None = None) -> int:
    created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    return max(1, math.ceil((now - created).total_seconds() / 3600))  # every started hour is billed in full


def sessions() -> list:
    # ponytail: one page of 50 servers; page through if we ever run more sessions than that at once
    return call("GET", "/servers?per_page=50&label_selector=" + urllib.parse.quote("oraculum=session"))["servers"]


def find(name: str) -> dict:
    found = call("GET", "/servers?name=" + urllib.parse.quote(name))["servers"]
    if not found:
        sys.exit(f"no server named {name}")
    return found[0]


def ipv4(server: dict) -> str:
    return (server["public_net"].get("ipv4") or {}).get("ip") or "-"


def cmd_prices(location: str) -> None:
    types = call("GET", "/server_types?per_page=50")["server_types"]
    print(f"{'type':8} {'cpu':9} {'vCPU':>4} {'RAM':>6}  {'EUR/h net':>9} {'EUR/h gross':>11}   location {location}")
    for t in sorted(types, key=lambda t: (t["cpu_type"], t["cores"], t["name"])):
        net, gross = price(t, location)
        if net is not None and not t.get("deprecated") and not t.get("deprecation"):
            print(f"{t['name']:8} {t['cpu_type']:9} {t['cores']:>4} {t['memory']:>4.0f}GB  {net:>9.4f} {gross:>11.4f}")


def cmd_list() -> None:
    rows = sessions()
    if not rows:
        print("no session servers: nothing bills except the snapshots")
    for s in rows:
        loc = (s.get("location") or (s.get("datacenter") or {}).get("location") or {}).get("name", "?")
        net, _ = price(s["server_type"], loc)
        h = billed_hours(s["created"])
        print(f"{s['name']:22} {s['status']:9} {s['server_type']['name']:6} {loc:5} {ipv4(s):15} "
              f"{h} h billed so far = EUR {h * (net or 0):.2f} net")


def cmd_images() -> None:
    imgs = call("GET", "/images?type=snapshot&label_selector=" + urllib.parse.quote("oraculum=golden"))["images"]
    if not imgs:
        print("no golden snapshot yet")
    for i in imgs:
        gb = i.get("image_size") or 0
        print(f"{i['id']}  {i['created'][:16]}  {gb:.1f} GB = EUR {gb * SNAPSHOT_EUR_GB_MONTH:.2f}/month  {i['description']}")


def network_id(name: str) -> int:
    """The private network `name` (free of charge), created with 10.0.0.0/16 if missing. Traffic on it bypasses the
    firewall, which filters only the public interface: it links the servers of one split session."""
    found = call("GET", "/networks?name=" + urllib.parse.quote(name))["networks"]
    if found:
        return found[0]["id"]
    return call("POST", "/networks", {"name": name, "ip_range": "10.0.0.0/16", "labels": {"oraculum": "network"},
                                      "subnets": [{"type": "cloud", "ip_range": "10.0.0.0/24",
                                                   "network_zone": "eu-central"}]})["network"]["id"]


def cmd_create(name: str, stype: str, image: str, location: str, user_data: str | None, yes: bool,
               network: str | None = None) -> None:
    found = call("GET", "/server_types?name=" + urllib.parse.quote(stype))["server_types"]
    if not found:
        sys.exit(f"unknown server type {stype}")
    t = found[0]
    net, gross = price(t, location)
    if net is None:
        sys.exit(f"{stype} is not offered in {location}")
    keys = [k["id"] for k in call("GET", "/ssh_keys")["ssh_keys"]]
    if not keys:
        sys.exit("no SSH key in the project: add one with sshkey-add first (without one Hetzner mails a root password)")
    fw = call("GET", "/firewalls?name=" + urllib.parse.quote(FIREWALL))["firewalls"]
    if not fw:
        sys.exit(f"no firewall {FIREWALL}: create it first with `hetzner.py firewall` (never an unfiltered server)")
    print(f"{name}: {stype} ({t['cores']} {t['cpu_type']} vCPU, {t['memory']:.0f} GB) in {location}, image {image}, "
          f"firewall {FIREWALL}: EUR {net:.4f}/h net ({gross:.4f} gross), each started hour billed until deleted")
    if not yes:
        print("dry run: nothing created. Add --yes to create it.")
        return
    body = {"name": name, "server_type": stype, "image": int(image) if image.isdigit() else image,
            "location": location, "labels": SESSION, "ssh_keys": keys, "start_after_create": True,
            "firewalls": [{"firewall": fw[0]["id"]}]}
    if network:
        body["networks"] = [network_id(network)]
    if user_data:
        body["user_data"] = pathlib.Path(user_data).read_text()
    r = call("POST", "/servers", body)  # with SSH keys set, the reply carries no root password
    wait(r["action"], f"create {name}")
    s = call("GET", f"/servers/{r['server']['id']}")["server"]
    private = " ".join(n["ip"] for n in s.get("private_net", []))
    print(f"created {name} (id {s['id']}) at {ipv4(s)}{' private ' + private if private else ''}. It bills until: python3 hosted/hetzner.py delete {name}")


def cmd_delete(name: str) -> None:
    s = find(name)
    if s["labels"].get("oraculum") != "session":
        sys.exit(f"{name} has no label oraculum=session: not an oraculum session server, not deleting it")
    wait(call("DELETE", f"/servers/{s['id']}")["action"], f"delete {name}")
    print(f"deleted {name}: its billing stopped")


def cmd_snapshot(name: str, description: str) -> None:
    s = find(name)
    r = call("POST", f"/servers/{s['id']}/actions/create_image",
             {"type": "snapshot", "description": description, "labels": GOLDEN})
    wait(r["action"], f"snapshot of {name}", timeout_s=3600)
    img = call("GET", f"/images/{r['image']['id']}")["image"]
    gb = img.get("image_size") or 0
    print(f"snapshot {img['id']} '{description}': {gb:.1f} GB compressed = EUR {gb * SNAPSHOT_EUR_GB_MONTH:.2f}/month")


def reap_candidates(servers: list, now: datetime, max_minutes: float) -> list:
    """(server, age in minutes) for every oraculum session server older than max_minutes. Only label oraculum=session."""
    out = []
    for s in servers:
        if s.get("labels", {}).get("oraculum") != "session":
            continue
        age = (now - datetime.fromisoformat(s["created"].replace("Z", "+00:00"))).total_seconds() / 60
        if age > max_minutes:
            out.append((s, age))
    return out


def cmd_reap(max_minutes: float) -> None:
    for s, age in reap_candidates(sessions(), datetime.now(timezone.utc), max_minutes):
        wait(call("DELETE", f"/servers/{s['id']}")["action"], f"reap {s['name']}")
        print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} reaped {s['name']} ({s['server_type']['name']}) after {age:.0f} min",
              flush=True)


def cmd_firewall() -> None:
    if call("GET", "/firewalls?name=" + urllib.parse.quote(FIREWALL))["firewalls"]:
        print(f"firewall {FIREWALL} exists")
        return
    rule = {"direction": "in", "protocol": "tcp", "port": "22", "source_ips": ["0.0.0.0/0", "::/0"], "description": "ssh"}
    call("POST", "/firewalls", {"name": FIREWALL, "labels": {"oraculum": "firewall"}, "rules": [rule]})
    print(f"created firewall {FIREWALL}: inbound TCP 22 only, outbound open (free)")


def cmd_sshkey(name: str, path: str) -> None:
    pub = pathlib.Path(path).expanduser().read_text().strip()
    if "PRIVATE KEY" in pub:
        sys.exit("that is a private key: pass the .pub file")
    call("POST", "/ssh_keys", {"name": name, "public_key": pub})
    print(f"added SSH key {name}")


def selftest() -> None:
    """Billing arithmetic and price lookup, no network."""
    start = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
    iso = start.isoformat()
    assert billed_hours(iso, start) == 1                            # a server that just appeared: 1 h minimum
    assert billed_hours(iso, start + timedelta(minutes=20)) == 1
    assert billed_hours(iso, start + timedelta(minutes=60)) == 1
    assert billed_hours(iso, start + timedelta(minutes=61)) == 2    # the second hour started: billed in full
    st = {"prices": [{"location": "nbg1", "price_hourly": {"net": "0.2227", "gross": "0.2717"}}]}
    assert price(st, "nbg1") == (0.2227, 0.2717)
    assert price(st, "fsn1") == (None, None)
    # reap: only labelled session servers, only past the limit
    srv = lambda name, minutes, label: {"name": name, "labels": {"oraculum": label} if label else {},  # noqa: E731
                                        "created": (start - timedelta(minutes=minutes)).isoformat()}
    fleet = [srv("old", 200, "session"), srv("young", 30, "session"), srv("foreign", 999, None), srv("gold", 999, "golden")]
    picked = [s["name"] for s, _ in reap_candidates(fleet, start, 180)]
    assert picked == ["old"], picked
    print("hetzner selftest OK")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="hosted oraculum sessions on Hetzner Cloud (pay only while running)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    sub.add_parser("list")
    sub.add_parser("images")
    sub.add_parser("firewall")
    p = sub.add_parser("prices")
    p.add_argument("--location", default="nbg1")
    c = sub.add_parser("create")
    c.add_argument("name")
    c.add_argument("--type", default="ccx33")
    c.add_argument("--image", default="ubuntu-24.04")
    c.add_argument("--location", default="nbg1")
    c.add_argument("--user-data")
    c.add_argument("--network", help="attach to this private network (created if missing; networks are free)")
    c.add_argument("--yes", action="store_true", help="really create it (it bills each started hour until deleted)")
    sub.add_parser("delete").add_argument("name")
    sn = sub.add_parser("snapshot")
    sn.add_argument("name")
    sn.add_argument("description")
    r = sub.add_parser("reap")
    r.add_argument("--max-minutes", type=float, required=True)
    k = sub.add_parser("sshkey-add")
    k.add_argument("name")
    k.add_argument("path")
    a = ap.parse_args()
    {"selftest": selftest, "list": cmd_list, "images": cmd_images, "firewall": cmd_firewall,
     "prices": lambda: cmd_prices(a.location),
     "create": lambda: cmd_create(a.name, a.type, a.image, a.location, a.user_data, a.yes, a.network),
     "delete": lambda: cmd_delete(a.name),
     "snapshot": lambda: cmd_snapshot(a.name, a.description),
     "reap": lambda: cmd_reap(a.max_minutes),
     "sshkey-add": lambda: cmd_sshkey(a.name, a.path)}[a.cmd]()
