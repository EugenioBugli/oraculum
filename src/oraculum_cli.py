import sys
import argparse
import urllib.request
import urllib.error
import json

SERVER_URL = "http://localhost:8080"


def get_state():
    try:
        with urllib.request.urlopen(f"{SERVER_URL}/state", timeout=1.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"Error connecting to Control Server at {SERVER_URL}: {e}")
        sys.exit(1)


def post_control(payload):
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/control",
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=1.0) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f"Error sending command to Control Server at {SERVER_URL}: {e}")
        sys.exit(1)


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
    post_control(payload)
    print(f"Sent walk command to robot at {args.ip}:{args.port} -> vx={args.vx}, vy={args.vy}, vtheta={args.vtheta}")


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
    print(f"Sent stiffness command to robot at {args.ip}:{args.port} -> stiffness mode: {args.mode}")


def do_stop(args):
    payload = {
        "ip": args.ip,
        "port": args.port,
        "vx": 0.0,
        "vy": 0.0,
        "vtheta": 0.0,
        "isManual": False,
        "lt": False
    }
    post_control(payload)
    print(f"Sent STOP manual override to robot at {args.ip}:{args.port}")


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

    # Stiffness command
    stiff_parser = subparsers.add_parser("stiffness", help="Toggle arm stiffness gains")
    stiff_parser.add_argument("mode", choices=["stiff", "limp"], help="Desired stiffness mode")
    stiff_parser.add_argument("--ip", default="127.0.0.1", help="Target robot IP (default: 127.0.0.1)")
    stiff_parser.add_argument("--port", type=int, default=10007, help="Target robot port (default: 10007)")

    # Stop command
    stop_parser = subparsers.add_parser("stop", help="Relinquish manual override and stop")
    stop_parser.add_argument("--ip", default="127.0.0.1", help="Target robot IP (default: 127.0.0.1)")
    stop_parser.add_argument("--port", type=int, default=10007, help="Target robot port (default: 10007)")

    args = parser.parse_args()

    if args.command == "status":
        do_status(args)
    elif args.command == "walk":
        do_walk(args)
    elif args.command == "stiffness":
        do_stiffness(args)
    elif args.command == "stop":
        do_stop(args)


if __name__ == "__main__":
    main()
