#!/usr/bin/env python3
"""Re-certification of oraculum MANUAL (Manual.cpp streams the sticks as Walk while oraculumManualActive()).
Run with measure_rtf.sh GC_STATES="" (game in INITIAL).
  3) INITIAL: vx 0.3 for 6 s (metres along the start heading), vtheta 0.5 for 4 s (heading change), vy 0.3 for 4 s
     (metres sideways), release: the robot must return to autonomous (stands in INITIAL).
  4) PLAYING (testingOverride): after 10 s of autonomous play, vtheta 0.5 for 4 s then vx 0.3 for 5 s: heading and
     motion must follow the commands; release: autonomous play resumes.
    python3 cert_test3.py [--ip 172.21.1.12]
"""
import argparse
import math
import time

from cert_test import CLIENT, agent, call, path_len, watch


def drive(ip, seconds, vx=0.0, vy=0.0, vtheta=0.0):
    a0, _ = agent(ip)
    t0, codes = time.time(), {}
    while time.time() - t0 < seconds:
        code, _ = call("/control", {"ip": ip, "port": 10007, "vx": vx, "vy": vy, "vtheta": vtheta, "isManual": True,
                                    "testingOverride": True, "client": CLIENT, "operator": "cert"})
        codes[code] = codes.get(code, 0) + 1
        time.sleep(0.1)
    a1, _ = agent(ip)
    h = a0.get("angle") or 0
    dx, dy = a1["x"] - a0["x"], a1["y"] - a0["y"]
    fwd = dx * math.cos(h) + dy * math.sin(h)
    side = -dx * math.sin(h) + dy * math.cos(h)
    dh = math.degrees(math.atan2(math.sin((a1.get("angle") or 0) - h), math.cos((a1.get("angle") or 0) - h)))
    return {"codes": codes, "fwd": round(fwd, 2), "side": round(side, 2), "dheading_deg": round(dh, 1),
            "fallen": bool(a1.get("fallen"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.21.1.12")
    ip = ap.parse_args().ip
    while agent(ip)[0] is None:
        time.sleep(1)
    time.sleep(15)
    still = watch(ip, 3)
    print("lock:", call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"})[0], flush=True)
    f = drive(ip, 6, vx=0.3)
    t = drive(ip, 4, vtheta=0.5)
    s = drive(ip, 4, vy=0.3)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    after = watch(ip, 8)
    ok = f["fwd"] > 0.3 and t["dheading_deg"] > 15 and abs(s["side"]) > 0.15 and path_len(after[6:]) < 0.15 \
        and not any(x[3] for x in still + after) and not (f["fallen"] or t["fallen"] or s["fallen"])
    print(f"STEP 3 (MANUAL from INITIAL): {'PASS' if ok else 'FAIL'} - before: moved {path_len(still):.2f} m in 3 s; "
          f"vx 0.3 6 s: {f}; vtheta 0.5 4 s: {t}; vy 0.3 4 s: {s}; after release: moved {path_len(after[6:]):.2f} m in "
          f"the last 5 s, fallen samples {sum(x[3] for x in after)}", flush=True)

    for st in ("ready", "set", "playing"):
        call("/gc", {"state": st})
        time.sleep(2)
    auto = watch(ip, 10)
    call("/control_lock", {"action": "take", "client": CLIENT, "name": "cert"})
    t2 = drive(ip, 4, vtheta=0.5)
    f2 = drive(ip, 5, vx=0.3)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "cert"})
    back = watch(ip, 12)
    ok4 = t2["dheading_deg"] > 15 and f2["fwd"] > 0.3 and path_len(back) > 0.5 and not any(x[3] for x in auto + back) \
        and not (t2["fallen"] or f2["fallen"])
    print(f"STEP 4 (MANUAL during PLAYING): {'PASS' if ok4 else 'FAIL'} - autonomous before: walked {path_len(auto):.1f} m "
          f"in 10 s; vtheta 0.5 4 s: {t2}; vx 0.3 5 s: {f2}; after release: walked {path_len(back):.1f} m in 12 s, "
          f"fallen samples {sum(x[3] for x in auto + back)}", flush=True)


if __name__ == "__main__":
    main()
