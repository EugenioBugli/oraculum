#!/usr/bin/env python3
"""Watch a running session through the gateway: roles, team colours, motion and falls of every robot over time.

Answers the questions of a play test: do the roles vary and change (team coordination), do both teams show their own
colour, and do the robots keep moving minutes into PLAYING. Runs on the session VM next to the gateway:
    python3 /opt/session/monitor_play.py [--seconds 150] [--every 10]
"""
import argparse
import json
import os
import time
import urllib.request

LEG = ["Left_Hip_Pitch", "Left_Knee_Pitch", "Left_Ankle_Pitch", "Right_Hip_Pitch", "Right_Knee_Pitch", "Right_Ankle_Pitch"]


def state(tok: str) -> dict:
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:8080/state?token={tok}", timeout=5))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=150)
    ap.add_argument("--every", type=float, default=10)
    a = ap.parse_args()
    tok = open(os.environ.get("ORACULUM_TOKEN_FILE", "/run/oraculum/token")).read().strip()  # Jetson: ~/oraculum-sim-arm/run/token
    while state(tok).get("gamecontroller", {}).get("state") != "PLAYING":   # wait for kickoff
        time.sleep(1)
    t0 = time.time()
    roles_seen, moving_late = {}, {}
    print("t(s) | GC | per robot: team colour role moving(range rad) walked(m in the interval) fallen")
    while time.time() - t0 < a.seconds:
        window, start = {}, {}
        end = time.time() + a.every
        last = None
        while time.time() < end:
            last = state(tok)
            for ag in last["agents"]:
                window.setdefault(ag["ip"], []).append([ag.get("joints", {}).get(k, 0) for k in LEG])
                start.setdefault(ag["ip"], (ag.get("x") or 0, ag.get("y") or 0))
            time.sleep(0.5)
        t = time.time() - t0
        cells = []
        for ag in sorted(last["agents"], key=lambda g: (g.get("team", 0), g.get("id", 0))):
            s = window.get(ag["ip"], [])
            rng = max((max(x[i] for x in s) - min(x[i] for x in s) for i in range(len(LEG))), default=0)
            x0, y0 = start.get(ag["ip"], (0, 0))
            walked = ((ag.get("x") or 0) - x0) ** 2 + ((ag.get("y") or 0) - y0) ** 2  # field metres, squared
            roles_seen.setdefault(ag["ip"], set()).add(ag.get("role"))
            if t > 120:
                moving_late[ag["ip"]] = moving_late.get(ag["ip"], False) or rng > 0.05
            cells.append(f"T{ag.get('team')}R{ag.get('id')} {ag.get('color', '?')[:1]} {ag.get('role')} "
                         f"{'mv' if rng > 0.05 else '--'}{rng:.2f} {walked ** 0.5:.1f}m{' FALLEN' if ag.get('fallen') else ''}")
        print(f"{t:5.0f} | {last.get('gamecontroller', {}).get('state')} | " + " ; ".join(cells), flush=True)
    print("\nroles seen per robot:", {ip: sorted(r) for ip, r in sorted(roles_seen.items())})
    print("distinct roles overall:", sorted({r for rs in roles_seen.values() for r in rs}))
    print("colours:", sorted({ag.get("color") for ag in state(tok)["agents"]}))
    if moving_late:
        print(f"moving after 120 s: {sum(moving_late.values())}/{len(moving_late)} robots")


if __name__ == "__main__":
    main()
