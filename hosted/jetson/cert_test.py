#!/usr/bin/env python3
"""Certification test of a robot tree in the Jetson simulation, through the oraculum gateway (stdlib only).

Runs next to measure_rtf.sh (which sends READY/SET/PLAYING). Steps, each printed with PASS/FAIL and the evidence:
  3. play:   in PLAYING the robot stands, walks (self-pose moves), has a team and a role, does not fall.
  4. manual: an oraculum MANUAL walk (POST /control, isManual, vx 0.3, testingOverride because the game is PLAYING)
             moves the robot; after the last packet it returns to autonomous play.
  5. stop:   POST /stop kind=stop holds the robot (no walking, no fall); kind=resume makes it play again, no fall.
    ORACULUM_TOKEN_FILE=~/oraculum-sim-arm/run/token python3 cert_test.py [--ip 172.21.1.12]
"""
import argparse
import json
import math
import os
import time
import urllib.request

URL = "http://127.0.0.1:8080"
TOKEN = open(os.environ.get("ORACULUM_TOKEN_FILE", os.path.expanduser("~/oraculum-sim-arm/run/token"))).read().strip()
CLIENT = "cert-test"


def call(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f"{URL}{path}?token={TOKEN}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode(errors="replace")[:200]}


def agent(ip):
    _, st = call("/state")
    return next((a for a in st.get("agents", []) if a.get("ip") == ip), None), st


def watch(ip, seconds):
    """Samples every 0.5 s: (t, x, y, fallen, state, role)."""
    out, t0 = [], time.time()
    while time.time() - t0 < seconds:
        a, _ = agent(ip)
        if a:
            out.append((time.time() - t0, a.get("x") or 0, a.get("y") or 0, bool(a.get("fallen")), a.get("state"), a.get("role")))
        time.sleep(0.5)
    return out


def path_len(s):
    return sum(math.dist(a[1:3], b[1:3]) for a, b in zip(s, s[1:]))


def report(step, ok, why):
    print(f"STEP {step}: {'PASS' if ok else 'FAIL'} - {why}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.21.1.12")
    ip = ap.parse_args().ip
    while (agent(ip)[1].get("gamecontroller") or {}).get("state") != "PLAYING":
        time.sleep(1)
    time.sleep(3)

    s = watch(ip, 20)
    a, _ = agent(ip)
    falls = sum(1 for x in s if x[3])
    report(3, bool(s) and falls == 0 and path_len(s) > 1.0 and a and a.get("team") is not None and a.get("role"),
           f"20 s PLAYING: walked {path_len(s):.1f} m, fallen samples {falls}/{len(s)}, team {a and a.get('team')} "
           f"colour {a and a.get('color')} role {a and a.get('role')} state {a and a.get('state')}")

    print("manual lock:", call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"}), flush=True)
    before, _ = agent(ip)
    t0, codes, states = time.time(), {}, set()
    while time.time() - t0 < 6:
        code, _ = call("/control", {"ip": ip, "port": 10007, "vx": 0.3, "vy": 0, "vtheta": 0, "isManual": True,
                                    "testingOverride": True, "client": CLIENT, "operator": "cert"})
        codes[code] = codes.get(code, 0) + 1
        a, _ = agent(ip)
        if a:
            states.add(a.get("state"))
        time.sleep(0.1)
    after, _ = agent(ip)
    d = math.dist((before["x"], before["y"]), (after["x"], after["y"]))
    head = before.get("angle") or 0
    along = (after["x"] - before["x"]) * math.cos(head) + (after["y"] - before["y"]) * math.sin(head)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    s2 = watch(ip, 12)
    report(4, codes.get(200, 0) > 0 and along > 0.2 and not any(x[3] for x in s2),
           f"/control replies {codes}; moved {d:.2f} m ({along:.2f} m forward along the start heading) in 6 s; "
           f"states seen during MANUAL {sorted(map(str, states))}; after release: walked {path_len(s2):.1f} m in 12 s, "
           f"states {sorted({str(x[4]) for x in s2})}, fallen samples {sum(1 for x in s2 if x[3])}")

    print("stop:", call("/stop", {"robot": ip, "kind": "stop", "client": CLIENT, "name": "cert", "confirm": ip}), flush=True)
    s3 = watch(ip, 10)
    held = path_len(s3[4:]) if len(s3) > 4 else 0
    print("resume lock:", call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"}), flush=True)
    print("resume:", call("/stop", {"robot": ip, "kind": "resume", "client": CLIENT, "name": "cert", "confirm": ip}), flush=True)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    s4 = watch(ip, 15)
    report(5, held < 0.3 and not any(x[3] for x in s3 + s4) and path_len(s4) > 0.5,
           f"after STOP: moved {held:.2f} m in the last 8 s, states {sorted({str(x[4]) for x in s3})}; after RESUME: "
           f"walked {path_len(s4):.1f} m in 15 s, states {sorted({str(x[4]) for x in s4})}; "
           f"fallen samples {sum(1 for x in s3 + s4 if x[3])}")


if __name__ == "__main__":
    main()
