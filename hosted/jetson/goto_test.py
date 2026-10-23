#!/usr/bin/env python3
"""Test of the oraculum GET UP / SIT DOWN / GO TO commands in the Jetson simulation (stdlib only, Python 3.10).
Run next to measure_rtf.sh with GC_STATES="" (game in INITIAL), 1 robot (scenes/1v0.yaml):
    GC_STATES="" RUN_NAME=GOTO1 SCENE=~/oraculum-sim-arm/scenes/1v0.yaml SIM_S=600 ./measure_rtf.sh &
    python3 goto_test.py [--ip 172.21.1.12]
Steps (each printed PASS/FAIL with numbers):
  A getup on a standing robot     B sit on a T1: 409 (T2 only)      C LIE DOWN, then getup
  D DAMP -> STOP -> getup          E goto ready_1                    F goto sideline_2
  G goto + cancel after 4 s        H resume -> autonomous again      I HTTP codes: 423 / 409 match / 403 PLAYING
Poses are the robot's self-pose from /state; in sim_fast that is circus's ground truth (OracleBridge).
"""
import argparse
import json
import math
import socket
import threading
import time
import urllib.request

from cert_test import CLIENT, TOKEN, URL, agent, call, path_len

FAKE_IP = "127.0.0.2"  # a fake match-mode robot (sys.link "telemetry") for the 409 check


def stop(ip, kind, client=CLIENT, **extra):
    return call("/stop", {"robot": ip, "kind": kind, "client": client, "name": "goto-test", "confirm": ip, **extra})


def sample(ip):
    a, st = agent(ip)
    return a or {}, st


def wait_for(ip, cond, timeout):
    """Polls /state every 0.5 s until cond(agent) or timeout; returns (seconds, agent, samples)."""
    t0, samples = time.time(), []
    while time.time() - t0 < timeout:
        a, _ = sample(ip)
        samples.append((time.time() - t0, a.get("x") or 0, a.get("y") or 0, bool(a.get("fallen")), a.get("latch"), a.get("angle")))
        if a and cond(a):
            return time.time() - t0, a, samples
        time.sleep(0.5)
    return None, sample(ip)[0], samples


def watch(ip, seconds):
    return wait_for(ip, lambda a: False, seconds)[2]


def ang(d):
    return math.atan2(math.sin(d), math.cos(d))


def report(step, ok, why):
    print(f"STEP {step}: {'PASS' if ok else 'FAIL'} - {why}", flush=True)


def fake_robot(stop_evt):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((FAKE_IP, 0))
    pkt = json.dumps({"agents": [{"id": 9, "team": 1, "x": -3, "y": 3, "angle": 0, "color": "red",
                                  "sys": {"link": "telemetry"}}]}).encode()
    while not stop_evt.is_set():
        s.sendto(pkt, ("127.0.0.1", 10006))
        time.sleep(0.2)


def positions(ip):
    """GET /positions?robot=<ip> (cert_test.call appends ?token=, so the query is built here)."""
    with urllib.request.urlopen(f"{URL}/positions?robot={ip}&token={TOKEN}", timeout=5) as r:
        return json.loads(r.read())


def goto_step(step, ip, pos, timeout=150):
    p = positions(ip)
    tgt = next(q for q in p["positions"] if q["id"] == pos)
    a0, _ = sample(ip)
    code, body = call("/goto", {"robot": ip, "pos": pos, "client": CLIENT, "name": "goto-test"})
    dist0 = math.dist((a0["x"], a0["y"]), (tgt["x"], tgt["y"]))
    seen_goto = wait_for(ip, lambda a: a.get("latch") == "goto" and isinstance(a.get("goto"), dict)
                         and abs(a["goto"].get("x", 99) - tgt["x"]) < 0.01 and abs(a["goto"].get("y", 99) - tgt["y"]) < 0.01, 5)[1]

    def arrived(a):
        return math.dist((a["x"], a["y"]), (tgt["x"], tgt["y"])) < 0.3 and abs(ang(a["angle"] - tgt["theta"])) < 0.52
    t_arr, _, samples = wait_for(ip, arrived, timeout)
    settle = watch(ip, 6)
    a1 = sample(ip)[0]
    ex, ey = a1["x"] - tgt["x"], a1["y"] - tgt["y"]
    eth = math.degrees(ang(a1["angle"] - tgt["theta"]))
    falls = sum(1 for s in samples + settle if s[3])
    g = seen_goto.get("goto") or {}
    ok = code == 200 and t_arr is not None and math.hypot(ex, ey) < 0.6 and abs(eth) < 60 and path_len(settle[-6:]) < 0.15 \
        and a1.get("latch") == "goto" and abs(g.get("x", 99) - tgt["x"]) < 0.01
    report(step, ok, f"goto {pos} {tgt['x']:.2f},{tgt['y']:.2f},{tgt['theta']:.2f}: HTTP {code} {body}; telemetry goto {g}; "
           f"start {a0['x']:.2f},{a0['y']:.2f} ({dist0:.1f} m); arrived (0.3 m / 30 deg) after "
           f"{'-' if t_arr is None else f'{t_arr:.1f}'} s wall; final error {math.hypot(ex, ey):.3f} m "
           f"(dx {ex:+.3f}, dy {ey:+.3f}), heading {eth:+.1f} deg; moved {path_len(settle[-6:]):.2f} m in the last 3 s; "
           f"fallen samples {falls}; latch {a1.get('latch')!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="172.21.1.12")
    ip = ap.parse_args().ip
    while agent(ip)[0] is None:
        time.sleep(1)
    time.sleep(15)
    print("lock:", call("/control_lock", {"action": "take", "client": CLIENT, "name": "goto-test"})[0], flush=True)
    t_start = time.time()

    # A getup on a standing robot
    a0, _ = sample(ip)
    code, _ = stop(ip, "getup")
    s = watch(ip, 6)
    a1, _ = sample(ip)
    report("A", code == 200 and a1.get("latch") == "getup" and not any(x[3] for x in s) and path_len(s) < 0.15,
           f"getup on standing: HTTP {code}, latch {a1.get('latch')!r}, moved {path_len(s):.2f} m in 6 s, "
           f"fallen samples {sum(x[3] for x in s)}")

    # B sit on a T1: refused (sit exists only on the T2, user decision 2026-10-23)
    code, body = stop(ip, "sit")
    a1, _ = sample(ip)
    report("B", code == 409 and a1.get("robot") != "t2" and not a1.get("fallen"),
           f"sit on a {a1.get('robot')!r}: HTTP {code} {body}, latch {a1.get('latch')!r}, fallen {a1.get('fallen')}")

    # C LIE DOWN, then getup from lying on the back
    code_l, _ = stop(ip, "lie")
    t_down, a, s = wait_for(ip, lambda a: a.get("fallen"), 20)
    time.sleep(4)
    a_l, _ = sample(ip)
    code, _ = stop(ip, "getup")
    t_up, a, s = wait_for(ip, lambda a: not a.get("fallen"), 60)
    s2 = watch(ip, 6)
    a1, _ = sample(ip)
    report("C", code_l == 200 and t_down is not None and code == 200 and t_up is not None and not any(x[3] for x in s2)
           and a1.get("latch") == "getup" and path_len(s2) < 0.3,
           f"lie HTTP {code_l}: down after {'-' if t_down is None else f'{t_down:.1f}'} s, latch {a_l.get('latch')!r}; getup "
           f"HTTP {code}, standing after {'-' if t_up is None else f'{t_up:.1f}'} s wall, then 6 s: fallen samples "
           f"{sum(x[3] for x in s2)}, moved {path_len(s2):.2f} m, latch {a1.get('latch')!r}")

    # D DAMP -> STOP -> getup
    code_d, _ = stop(ip, "damp")
    t_fall, _, _ = wait_for(ip, lambda a: a.get("fallen"), 10)
    a_d, _ = sample(ip)
    code_g_damped, _ = stop(ip, "getup")  # refused: damped
    code_s, _ = stop(ip, "stop")
    time.sleep(3)
    a_s, _ = sample(ip)
    code_g, _ = stop(ip, "getup")
    t_up, a, s = wait_for(ip, lambda a: not a.get("fallen"), 60)
    s2 = watch(ip, 6)
    a1, _ = sample(ip)
    report("D", code_d == 200 and t_fall is not None and code_g_damped == 409 and code_s == 200 and code_g == 200 and t_up is not None
           and not any(x[3] for x in s2) and a1.get("latch") == "getup",
           f"DAMP HTTP {code_d}, fallen after {'-' if t_fall is None else f'{t_fall:.1f}'} s, latch {a_d.get('latch')!r}; "
           f"getup while damped HTTP {code_g_damped}; STOP HTTP {code_s}, latch {a_s.get('latch')!r}; getup HTTP {code_g}, "
           f"standing after {'-' if t_up is None else f'{t_up:.1f}'} s wall; then 6 s: fallen samples {sum(x[3] for x in s2)}, "
           f"moved {path_len(s2):.2f} m, latch {a1.get('latch')!r}")

    # E, F goto
    goto_step("E", ip, "ready_1")
    goto_step("F", ip, "sideline_2")

    # G goto + cancel
    code, body = call("/goto", {"robot": ip, "x": -4.0, "y": 0.0, "theta": 0.0, "client": CLIENT, "name": "goto-test"})
    s = watch(ip, 6)
    code_c, body_c = call("/goto", {"robot": ip, "cancel": True, "client": CLIENT, "name": "goto-test"})
    s2 = watch(ip, 6)
    a1, _ = sample(ip)
    report("G", code == 200 and code_c == 200 and path_len(s) > 0.3 and path_len(s2[-6:]) < 0.15 and a1.get("latch") == "getup"
           and a1.get("goto") is None and not any(x[3] for x in s + s2),
           f"goto (-4, 0) HTTP {code}: walked {path_len(s):.2f} m in 6 s; cancel HTTP {code_c} {body_c}: moved "
           f"{path_len(s2[-6:]):.2f} m in the last 3 s of 6, latch {a1.get('latch')!r}, goto {a1.get('goto')}")

    # H resume -> autonomous (INITIAL: stands), then PLAYING: plays
    code, _ = stop(ip, "resume")
    t_l, _, _ = wait_for(ip, lambda a: a.get("latch") == "", 5)
    for st in ("ready", "set", "playing"):
        call("/gc", {"state": st})
        time.sleep(2)
    s = watch(ip, 15)
    report("H", code == 200 and t_l is not None and path_len(s) > 1.0 and not any(x[3] for x in s),
           f"resume HTTP {code}, latch '' after {'-' if t_l is None else f'{t_l:.1f}'} s; READY/SET/PLAYING: walked "
           f"{path_len(s):.1f} m in 15 s, fallen samples {sum(x[3] for x in s)}")

    # I HTTP codes (game PLAYING now)
    stop_evt = threading.Event()
    threading.Thread(target=fake_robot, args=(stop_evt,), daemon=True).start()
    time.sleep(1.5)
    codes = {
        "getup PLAYING no override": stop(ip, "getup")[0],
        "goto PLAYING no override": call("/goto", {"robot": ip, "pos": "ready_2", "client": CLIENT})[0],
        "getup other client (lock)": stop(ip, "getup", client="someone-else")[0],
        "goto other client (lock)": call("/goto", {"robot": ip, "pos": "ready_2", "client": "someone-else"})[0],
        "getup match robot": stop(FAKE_IP, "getup")[0],
        "sit match robot": stop(FAKE_IP, "sit")[0],
        "goto match robot": call("/goto", {"robot": FAKE_IP, "pos": "ready_2", "client": CLIENT})[0],
        "goto bad pos": call("/goto", {"robot": ip, "pos": "nowhere", "client": CLIENT})[0],
    }
    a1, _ = sample(ip)
    still_playing = a1.get("latch") == ""
    codes["getup PLAYING testingOverride"] = stop(ip, "getup", testingOverride=True)[0]
    time.sleep(2)
    a2, _ = sample(ip)
    codes["resume"] = stop(ip, "resume")[0]
    stop_evt.set()
    want = {"getup PLAYING no override": 403, "goto PLAYING no override": 403,
            "getup other client (lock)": 423, "goto other client (lock)": 423, "getup match robot": 409,
            "sit match robot": 409, "goto match robot": 409, "goto bad pos": 400, "getup PLAYING testingOverride": 200,
            "resume": 200}
    report("I", codes == want and still_playing and a2.get("latch") == "getup",
           f"codes {codes}; latch after the refused commands {a1.get('latch')!r}; after the override getup {a2.get('latch')!r}")
    s = watch(ip, 8)
    print(f"after the last resume: walked {path_len(s):.1f} m in 8 s, fallen samples {sum(x[3] for x in s)}; "
          f"test wall time {time.time() - t_start:.0f} s", flush=True)
    call("/control_lock", {"action": "release", "client": CLIENT, "name": "goto-test"})


if __name__ == "__main__":
    main()
