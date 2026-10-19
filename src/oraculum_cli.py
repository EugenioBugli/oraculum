import argparse
import atexit
import getpass
import json
import secrets
import socket
import sys
import time
import urllib.error
import urllib.request

SERVER_URL = "http://localhost:8080"
# Engineer mode (src/control_lock.py): this run is one client; walk/stiffness need the control lock
CLIENT = f"cli-{secrets.token_hex(6)}"
OPERATOR = f"cli {getpass.getuser()}@{socket.gethostname()}"


def get_state():
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/state", timeout=1.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"Error connecting to Control Server at {SERVER_URL}: {e}")
        sys.exit(1)


def post(path, payload):
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}{path}",
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:  # 423: another operator has control; 409: no robot reached
        body = json.loads(e.read().decode('utf-8') or "{}")
        print(f"Refused ({e.code}): {body.get('reason') or body.get('error') or body}")
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
        urllib.request.urlopen(urllib.request.Request(
            f"{SERVER_URL}/control_lock", data=json.dumps({"action": "release", "client": CLIENT}).encode('utf-8'),
            headers={"Content-Type": "application/json"}), timeout=1.0).read()
    except Exception:
        pass


def do_status(args):
    state = get_state()

    print("\n=== GameController Match State ===")
    gc = state.get("gamecontroller")
    if gc:
        print(f"State: {gc['state']} | Score: {gc['score'][0]} - {gc['score'][1]} | Time remaining: {gc['secsRemaining']}s")
    else:
        print("No active GameController broadcast detected.")

    print("\n=== Connected Robots ===")
    agents = state.get("agents", [])
    if not agents:
        print("No robot status broadcasts received yet.")
    else:
        print(f"{'ID':<4} | {'X':<8} | {'Y':<8} | {'Heading':<8} | {'Role':<6} | {'State':<10}")
        print("-" * 55)
        for a in agents:
            print(f"{a['id']:<4} | {a['x']:<8.3f} | {a['y']:<8.3f} | {a['angle']:<8.3f} | {a['role']:<6} | {a['state']:<10}")

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


def do_stiffness(args):
    lt_val = (args.mode == "limp")
    payload = {
        "ip": args.ip,
        "port": args.port,
        "vx": 0.0,
        "vy": 0.0,
        "vtheta": 0.0,
        "isManual": True,
        "lt": lt_val
    }
    post_control(payload)
    release_lock()
    print(f"Sent stiffness command to robot at {args.ip}:{args.port} -> stiffness mode: {args.mode}")


def do_stop(args):
    """STOP (stand in the Prep pose), DAMP (motors soft) or RESUME (the Play combo) through POST /stop."""
    kind = args.command
    if kind == "damp" and not args.really:
        print("DAMP makes the robot fall. Repeat with --really to send it.")
        sys.exit(1)
    robot = "all" if getattr(args, "all", False) else args.ip
    reply = post("/stop", {"robot": robot, "kind": kind, "client": CLIENT, "name": OPERATOR, "confirm": robot})
    if kind == "resume":
        release_lock()
    print(f"Sent {kind.upper()} to {', '.join(reply['targets'])}")


def main():
    parser = argparse.ArgumentParser(description="Oraculum CLI Control Utility")
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

    # Stiffness command
    stiff_parser = subparsers.add_parser("stiffness", help="Toggle arm stiffness gains")
    stiff_parser.add_argument("mode", choices=["stiff", "limp"], help="Desired stiffness mode")
    stiff_parser.add_argument("--ip", default="127.0.0.1", help="Target robot IP (default: 127.0.0.1)")
    stiff_parser.add_argument("--port", type=int, default=10007, help="Target robot port (default: 10007)")

    # STOP / DAMP / RESUME: through POST /stop (STOP and DAMP need no control lock)
    for name, text in (("stop", "STOP: the robot stands in the Prep pose until RESUME or a Play/Manual combo"),
                       ("lie", "LIE DOWN: the firmware lays the robot on its back until RESUME"),
                       ("damp", "DAMP: motors soft, the robot FALLS and can break (one robot, needs --really)"),
                       ("resume", "RESUME: the Play combo (clears STOP and DAMP); needs the control lock")):
        sp = subparsers.add_parser(name, help=text)
        target = sp.add_mutually_exclusive_group(required=True)
        target.add_argument("--ip", help="robot IP (one that sends telemetry)")
        if name != "damp":  # DAMP is never sent to all robots
            target.add_argument("--all", action="store_true", help="every robot heard in the last 60 s")
        if name == "damp":
            sp.add_argument("--really", action="store_true")

    args = parser.parse_args()

    if args.command == "status":
        do_status(args)
    elif args.command == "walk":
        do_walk(args)
    elif args.command == "stiffness":
        do_stiffness(args)
    elif args.command in ("stop", "lie", "damp", "resume"):
        do_stop(args)


if __name__ == "__main__":
    main()
