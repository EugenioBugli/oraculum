import argparse
import atexit
import getpass
import json
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.request

# The gateway: ORACULUM_URL (default http://localhost:8080). A gateway started with ORACULUM_ACCESS_TOKEN needs the same
# token: the CLI sends it as the oraculum_token cookie, as the pages do after their first ?token= visit.
SERVER_URL = os.environ.get("ORACULUM_URL", "http://localhost:8080").rstrip("/")
TOKEN = os.environ.get("ORACULUM_ACCESS_TOKEN", "")
# Engineer mode (src/control_lock.py): this run is one client; walk and resume need the control lock
CLIENT = f"cli-{secrets.token_hex(6)}"
OPERATOR = f"cli {getpass.getuser()}@{socket.gethostname()}"


def request(path, payload=None):
    """A GET (no payload) or a JSON POST to the gateway, with the access token when one is set."""
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if TOKEN:
        headers["Cookie"] = f"oraculum_token={TOKEN}"
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    return urllib.request.Request(f"{SERVER_URL}{path}", data=data, headers=headers)


def refused(e):
    """Print why the gateway refused (HTTP 401: token; 423: another operator has control; 409: no robot reached)."""
    if e.code == 401:
        print(f"Refused (401): {SERVER_URL} needs its access token. Set ORACULUM_ACCESS_TOKEN to the token the gateway was started with.")
        return
    try:
        body = json.loads(e.read().decode('utf-8') or "{}")
    except ValueError:
        body = {}
    print(f"Refused ({e.code}): {body.get('reason') or body.get('error') or body or e.reason}")


def get_state():
    try:
        with urllib.request.urlopen(request("/state"), timeout=1.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        refused(e)
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to Control Server at {SERVER_URL}: {e}")
        sys.exit(1)


def post(path, payload):
    try:
        with urllib.request.urlopen(request(path, payload), timeout=2.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        refused(e)
        sys.exit(1)
    except Exception as e:
        print(f"Error sending command to Control Server at {SERVER_URL}: {e}")
        sys.exit(1)


def post_control(payload):
    return post("/control", dict(payload, client=CLIENT, operator=OPERATOR))


def release_lock():
    post("/control_lock", {"action": "release", "client": CLIENT, "name": OPERATOR})


@atexit.register
def _release_on_exit():  # also after a refused command: a CLI run never keeps the lock
    try:
        urllib.request.urlopen(request("/control_lock", {"action": "release", "client": CLIENT}), timeout=1.0).read()
    except Exception:
        pass


def do_status(args):
    state = get_state()

    print("\n=== GameController Match State ===")
    gc = state.get("gamecontroller")
    if gc and "state" in gc:  # without a GameController the gateway sends only {"external_gc_online": false}
        score = gc.get("score") or ["-", "-"]
        print(f"State: {gc['state']} | Score: {score[0]} - {score[1]} | Time remaining: {gc.get('secsRemaining', '-')}s")
    else:
        print("No active GameController broadcast detected.")

    print("\n=== Connected Robots ===")
    agents = state.get("agents", [])
    if not agents:
        print("No robot status broadcasts received yet.")
    else:
        # Link: seconds since the gateway's last packet from the robot's IP; 1 s or more = stale (old data, as the pages grey it)
        link = (state.get("fleet") or {}).get("link") or {}
        print(f"{'Robot':<8} | {'IP':<15} | {'X':<8} | {'Y':<8} | {'Heading':<8} | {'Role':<6} | {'State':<10} | Link")
        print("-" * 92)
        for a in agents:
            age = (link.get(a.get("ip")) or {}).get("age")
            age_text = "?" if age is None else f"{age:.1f} s" + (" STALE" if age >= 1 else "")
            print(f"{'T' + str(a.get('team', '?')) + ' R' + str(a['id']):<8} | {a.get('ip', '?'):<15} | {a['x']:<8.3f} | {a['y']:<8.3f} | "
                  f"{a['angle']:<8.3f} | {a['role']:<6} | {a['state']:<10} | {age_text}")

    print("\n=== Active Debug Drawings ===")
    drawings = state.get("drawings", [])
    if not drawings:
        print("No debug drawings currently in stream cache.")
    else:
        print(f"{'Type':<10} | {'Path':<30} | {'Coords Count':<12}")
        print("-" * 58)
        for dr in drawings:
            print(f"{dr['type']:<10} | {dr['path']:<30} | {len(dr['coords']):<12}")
    print()


def send_for(payload, seconds):
    """The robot drops UDP joystick input 500 ms after the last packet, so repeat at 10 Hz."""
    end = time.monotonic() + seconds
    while True:
        post_control(payload)
        if time.monotonic() >= end:
            break
        time.sleep(0.1)


def do_walk(args):
    payload = {
        "ip": args.ip,
        "port": args.port,
        "vx": args.vx,
        "vy": args.vy,
        "vtheta": args.vtheta,
        "isManual": True,
        "lt": False
    }
    send_for(payload, args.duration)
    release_lock()
    print(f"Sent walk command to robot at {args.ip}:{args.port} for {args.duration}s -> vx={args.vx}, vy={args.vy}, vtheta={args.vtheta}")


def do_stop(args):
    """STOP (stand in the Prep pose), DAMP (motors soft) or RESUME (the Play combo) through POST /stop."""
    kind = args.command
    if kind == "damp" and not args.really:
        print("DAMP makes the robot fall. Repeat with --really to send it.")
        sys.exit(1)
    robot = "all" if getattr(args, "all", False) else args.ip
    body = {"robot": robot, "kind": kind, "client": CLIENT, "name": OPERATOR, "confirm": robot}
    if getattr(args, "override", False):
        body["testingOverride"] = True
    reply = post("/stop", body)
    if kind in ("resume", "getup", "sit"):
        release_lock()
    print(f"Sent {kind.upper()} to {', '.join(reply.get('names') or reply['targets'])}")  # "T19 R3 (10.0.0.3)"


def do_goto(args):
    """GO TO through POST /goto: --x --y --theta (shared field frame), --pos <id of GET /positions>, or --cancel."""
    if args.list:
        for p in post_get("/positions" + (f"?robot={args.ip}" if args.ip else ""))["positions"]:
            print(f"{p['id']:<20} {p['x']:>7.2f} {p['y']:>7.2f} {p['theta']:>7.3f}  {p['label']}")
        return
    body = {"robot": args.ip, "client": CLIENT, "name": OPERATOR}
    if args.override:
        body["testingOverride"] = True
    if args.cancel:
        body["cancel"] = True
    elif args.pos:
        body["pos"] = args.pos
    elif None not in (args.x, args.y):
        body.update(x=args.x, y=args.y, theta=args.theta)
    else:
        print("goto needs --pos ID, --x X --y Y [--theta T], --cancel or --list")
        sys.exit(1)
    reply = post("/goto", body)
    release_lock()
    print(f"Sent GOTO {'cancel' if args.cancel else reply.get('target')} to {args.ip}")


def post_get(path):
    try:
        with urllib.request.urlopen(request(path), timeout=2.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        refused(e)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Oraculum CLI Control Utility",
        epilog="Gateway: ORACULUM_URL (default http://localhost:8080). Access token: ORACULUM_ACCESS_TOKEN (needed when the "
               "gateway was started with one).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Status command
    subparsers.add_parser("status", help="Query connected robots, game state, and drawings")

    # Walk command
    walk_parser = subparsers.add_parser("walk", help="Send manual walking velocities")
    walk_parser.add_argument("vx", type=float, help="Walk forward velocity (-1.0 to 1.0)")
    walk_parser.add_argument("vy", type=float, help="Strafe velocity (-1.0 to 1.0)")
    walk_parser.add_argument("vtheta", type=float, help="Rotational velocity (-1.0 to 1.0)")
    walk_parser.add_argument("--ip", default="127.0.0.1", help="Target robot IP (default: 127.0.0.1)")
    walk_parser.add_argument("--port", type=int, default=10007, help="Target robot port (default: 10007)")
    walk_parser.add_argument("--duration", type=float, default=1.0, help="Seconds to keep sending at 10 Hz (default: 1.0)")

    # No "stiffness" command: it only set the joystick's left trigger (lt), and the robot uses lt only in button
    # combos (lt + start = Prep), so the robot never went limp. To make a robot soft, use "damp" (it falls) or "lie".

    # STOP / DAMP / RESUME: through POST /stop (STOP and DAMP need no control lock)
    for name, text in (("stop", "STOP: the robot stands in the Prep pose until RESUME or a Play/Manual combo"),
                       ("lie", "LIE DOWN: the firmware lays the robot on its back until RESUME"),
                       ("damp", "DAMP: motors soft, the robot FALLS and can break (one robot, needs --really)"),
                       ("resume", "RESUME: the Play combo (clears STOP; a DAMPed robot needs STOP first); needs the control lock"),
                       ("getup", "GET UP: the robot gets up if it is down, then stands still until RESUME; needs the control lock"),
                       ("sit", "SIT DOWN: T2 only (other models: 409); needs the control lock")):
        sp = subparsers.add_parser(name, help=text, description=text)  # "resume -h" shows it too
        target = sp.add_mutually_exclusive_group(required=True)
        target.add_argument("--ip", help="robot IP (one that sends telemetry)")
        if name != "damp":  # DAMP is never sent to all robots
            target.add_argument("--all", action="store_true", help="every robot heard in the last 60 s")
        if name == "damp":
            sp.add_argument("--really", action="store_true")
        if name in ("getup", "sit"):
            sp.add_argument("--override", action="store_true", help="testingOverride: also in READY/SET/PLAYING")

    gp = subparsers.add_parser("goto", help="GO TO: walk one robot to a pose, then stand until RESUME (needs the control lock)")
    gp.add_argument("--ip", help="robot IP (one that sends telemetry)")
    gp.add_argument("--x", type=float, help="field frame, m")
    gp.add_argument("--y", type=float, help="field frame, m")
    gp.add_argument("--theta", type=float, default=0.0, help="field frame, rad (default 0)")
    gp.add_argument("--pos", help="a position id of GET /positions (e.g. ready_2, sideline_1), in the robot's own team frame")
    gp.add_argument("--cancel", action="store_true", help="stop the walk; the robot stands where it is")
    gp.add_argument("--list", action="store_true", help="print the positions (with --ip: in the field frame of its team)")
    gp.add_argument("--override", action="store_true", help="testingOverride: also in READY/SET/PLAYING")

    args = parser.parse_args()

    if args.command == "status":
        do_status(args)
    elif args.command == "walk":
        do_walk(args)
    elif args.command in ("stop", "lie", "damp", "resume", "getup", "sit"):
        do_stop(args)
    elif args.command == "goto":
        if not args.ip and not args.list:
            parser.error("goto needs --ip")
        do_goto(args)


if __name__ == "__main__":
    main()
