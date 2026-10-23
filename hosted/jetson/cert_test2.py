#!/usr/bin/env python3
"""Certification steps 4-5 without autonomous play in the way (measure_rtf.sh with GC_STATES="": game in INITIAL).
  a) MANUAL in INITIAL: vx 0.3 for 6 s through POST /control; the standing robot must walk forward; then stand.
  b) STOP and RESUME while standing (INITIAL).
  c) PLAYING, 15 s of play, then STOP while walking, 10 s, RESUME, 15 s: falls?
    python3 cert_test2.py [--ip 172.21.1.12]
"""
import argparse
import math
import time

from cert_test import CLIENT, agent, call, path_len, watch


def manual(ip, seconds, vx):
    t0, codes = time.time(), {}
    while time.time() - t0 < seconds:
        code, _ = call("/control", {"ip": ip, "port": 10007, "vx": vx, "vy": 0, "vtheta": 0, "isManual": True,
                                    "testingOverride": True, "client": CLIENT, "operator": "cert"})
        codes[code] = codes.get(code, 0) + 1
        time.sleep(0.1)
    return codes


def stop_resume(ip, tag, hold=10, after=15):
    print(f"{tag} stop:", call("/stop", {"robot": ip, "kind": "stop", "client": CLIENT, "name": "cert", "confirm": ip})[0], flush=True)
    s1 = watch(ip, hold)
    call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"})
    print(f"{tag} resume:", call("/stop", {"robot": ip, "kind": "resume", "client": CLIENT, "name": "cert", "confirm": ip})[0], flush=True)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    s2 = watch(ip, after)
    f1, f2 = sum(x[3] for x in s1), sum(x[3] for x in s2)
    first = next((x[0] for x in s1 if x[3]), None)
    print(f"{tag}: during STOP moved {path_len(s1[4:]):.2f} m (last {hold - 2} s), fallen samples {f1}/{len(s1)}"
          f"{f' (first at {first:.1f} s after STOP)' if first is not None else ''}; after RESUME walked {path_len(s2):.1f} m, "
          f"fallen samples {f2}/{len(s2)}", flush=True)
    return f1 + f2 == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.21.1.12")
    ip = ap.parse_args().ip
    while agent(ip)[0] is None:
        time.sleep(1)
    time.sleep(15)  # stand still in INITIAL

    s0 = watch(ip, 4)
    a0, _ = agent(ip)
    print("lock:", call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"})[0], flush=True)
    codes = manual(ip, 6, 0.3)
    a1, _ = agent(ip)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    s1 = watch(ip, 8)
    head = a0.get("angle") or 0
    fwd = (a1["x"] - a0["x"]) * math.cos(head) + (a1["y"] - a0["y"]) * math.sin(head)
    ok = codes.get(200, 0) > 0 and fwd > 0.3 and path_len(s0) < 0.2 and path_len(s1[4:]) < 0.3 and not any(x[3] for x in s0 + s1)
    print(f"STEP 4 (MANUAL, INITIAL): {'PASS' if ok else 'FAIL'} - before: moved {path_len(s0):.2f} m in 4 s; MANUAL vx 0.3 "
          f"for 6 s: /control {codes}, moved {fwd:.2f} m forward ({math.dist((a0['x'], a0['y']), (a1['x'], a1['y'])):.2f} m total); "
          f"after release: moved {path_len(s1[4:]):.2f} m in the last 4 s; fallen samples {sum(x[3] for x in s0 + s1)}", flush=True)

    ok_b = stop_resume(ip, "STEP 5b (standing, INITIAL)")
    for s in ("ready", "set", "playing"):
        call("/gc", {"state": s})
        time.sleep(2)
    s2 = watch(ip, 15)
    print(f"PLAYING 15 s: walked {path_len(s2):.1f} m, fallen samples {sum(x[3] for x in s2)}", flush=True)
    ok_c = stop_resume(ip, "STEP 5c (walking, PLAYING)")
    print(f"STEP 5: {'PASS' if ok_b and ok_c else 'FAIL'} - standing {'ok' if ok_b else 'FELL'}, walking {'ok' if ok_c else 'FELL'}", flush=True)


if __name__ == "__main__":
    main()
