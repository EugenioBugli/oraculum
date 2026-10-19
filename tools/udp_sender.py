"""Fake robots for the oraculum gateway: telemetry on UDP 10006 and camera frames on request.

Run this in a separate terminal while the gateway runs:
    python3 tools/udp_sender.py

Each robot sends its own packet, as DebugMessageSender does on a real robot: the agent with its fleet data
("sys"), plus its own ball estimate and the obstacles it sees as the packet's top-level "ball" / "obstacles".
Robot 1's packet also carries the debug drawings. Camera: like DebugCameraSender, it answers requests on
UDP 10008 (src/camera_hub.py) with synthetic camera images. The field lines in those images are drawn
with the camera model of the frame header, so the page's projected field lines must lie on them.

The host/port must match the [socket] section in config.yaml.
"""

import io
import json
import math
import os
import pathlib
import random
import socket
import subprocess
import sys
import threading
import time

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agents import AGENT_ROLES, AGENT_STATES, Agent, Ball, create_agents
from src.camera_hub import REQUEST_PORT, pack_frame

# ---------------------------------------------------------------------------
# Configuration — keep in sync with config.yaml [socket] section
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 10006
FPS  = 25

# Field half-dimensions in metres: circus's fieldLarge (14 x 9 m), the field of the
# "Circus (exact)" 3D view, so the fake robots stay on the circus field
HW = 7.0   # half-length (14 m)
HH = 4.5   # half-width  (9 m)

N_AGENTS = 7
TEAMS = {"#822433": 19, "#000000": 19, "#006778": 5, "#ffffff": 5}  # agent colour -> team number

# Synthetic camera: 320 x 240, head 1.1 m high, pitched 0.5 rad down
CAM_W, CAM_H, CAM_F = 320, 240, 190.0
CAM_HEIGHT, CAM_PITCH = 1.1, 0.5
CAM_FPS = 4


def _fake_joints(i: int) -> dict[str, float]:
    """Head scan and arm swing, so the WASM view shows posed joints."""
    t = time.monotonic() + i
    return {
        "AAHead_yaw": round(0.8 * math.sin(0.7 * t), 3),
        "Left_Shoulder_Pitch": round(0.5 * math.sin(3.0 * t), 3),
        "Right_Shoulder_Pitch": round(-0.5 * math.sin(3.0 * t), 3),
        "Left_Shoulder_Roll": -1.3,
        "Right_Shoulder_Roll": 1.3,
    }


def _fake_sys(i: int, t: float) -> dict:
    """Fleet data: robot 3 runs an old build, robot 5 records."""
    return {
        "version": "4ceb74f0" if i == 2 else HEAD,  # one robot runs an old build on purpose
        "cpu": round(35 + 20 * math.sin(0.3 * t + i), 1),
        "load": round(4 + 2 * math.sin(0.1 * t + i), 2),
        "temp": round(55 + 8 * math.sin(0.05 * t + i), 1),
        "tx": round(60 + 15 * math.sin(t + i), 1),
        "rx": round(8 + 3 * math.sin(0.7 * t + i), 1),
        "rec": i == 4,
    }


def _drawings(agents: list[Agent], ball: Ball) -> list[dict]:
    return [
        {"type": "circle", "path": "/field/center_circle", "coords": [0.0, 0.0], "color": [0, 210, 255], "size": 1.5},
        {"type": "box", "path": "/ball/bounding_box", "coords": [ball.x, ball.y, 0.6, 0.6], "color": [255, 60, 106], "size": 0.01},
        {"type": "line", "path": "/coordination/pass_line", "coords": [agents[0].x, agents[0].y, ball.x, ball.y],
         "color": [0, 255, 136], "size": 0.02},
        {"type": "point", "path": "/striker/target_pose", "coords": [3.5, 1.5], "color": [255, 255, 0], "size": 0.08},
        {"type": "arc", "path": "/goalie/view_arc", "coords": [-HW + 0.5, 0.0, 2.5, -45, 45], "color": [200, 200, 200], "size": 0.02},
    ]


def build_packets(agents: list[Agent], ball: Ball, t: float, rng: random.Random) -> list[dict]:
    """One packet per robot, as the real robots send them."""
    packets = []
    for i, a in enumerate(agents):
        agent = {"id": a.id, "x": round(a.x, 4), "y": round(a.y, 4), "angle": round(a.angle, 4), "role": a.role,
                 "state": a.state, "color": a.color, "joints": _fake_joints(i), "team": TEAMS.get(a.color, 0),
                 "battery": 18.0 if i == 6 else round(95 - (t / 60) % 50 - 3 * i, 1), "fallen": a.state == "X",
                 "sys": _fake_sys(i, t), "latch": LATCH["v"]}
        packet = {"agents": [agent]}
        # Own beliefs: a ball estimate with 0.1-0.4 m error (robot 4 does not see the ball) and nearby robots.
        if i != 3:
            err = 0.1 + 0.3 * (i / len(agents))
            packet["ball"] = {"x": round(ball.x + err * math.cos(t + i), 3), "y": round(ball.y + err * math.sin(t + i), 3)}
        packet["obstacles"] = [{"x": round(o.x + rng.uniform(-0.15, 0.15), 3), "y": round(o.y + rng.uniform(-0.15, 0.15), 3), "type": 2}
                               for o in agents if o is not a and math.hypot(o.x - a.x, o.y - a.y) < 4.0]
        if i == 0:
            packet["drawings"] = _drawings(agents, ball)
        packets.append(packet)
    return packets


# ---------------------------------------------------------------------------
# Synthetic camera
# ---------------------------------------------------------------------------

def _field_lines() -> list[list[tuple[float, float]]]:
    """Polylines of fieldAdultSize.yaml (14 x 9 m) in the field frame."""
    L, W, ga_w, ga_h, pa_w, pa_h = HW, HH, 1.0, 4.0, 3.0, 6.5

    def rect(x0, x1, h):
        return [(x0, -h), (x1, -h), (x1, h), (x0, h), (x0, -h)]

    lines = [rect(-L, L, W), [(0, -W), (0, W)],
             [(1.5 * math.cos(k * math.pi / 24), 1.5 * math.sin(k * math.pi / 24)) for k in range(49)]]
    for s in (-1, 1):
        lines += [rect(s * L, s * (L - ga_w), ga_h / 2), rect(s * L, s * (L - pa_w), pa_h / 2)]
        px = s * (L - 2.1)
        lines += [[(px - 0.05, 0), (px + 0.05, 0)], [(px, -0.05), (px, 0.05)]]
    return lines


class FakeCamera:
    """Camera of a robot at (x, y) looking along heading + head yaw; projects field points to pixels."""

    def __init__(self, x: float, y: float, yaw: float) -> None:
        cp, sp = math.cos(CAM_PITCH), math.sin(CAM_PITCH)
        self.c = (x, y, CAM_HEIGHT)
        self.fwd = (cp * math.cos(yaw), cp * math.sin(yaw), -sp)
        self.right = (math.sin(yaw), -math.cos(yaw), 0.0)
        f, r = self.fwd, self.right
        self.down = (f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0])  # z x x

    def transform(self) -> list[float]:
        """Camera-to-field 4x4, row-major (camera x right, y down, z forward)."""
        r, d, f, c = self.right, self.down, self.fwd, self.c
        return [r[0], d[0], f[0], c[0], r[1], d[1], f[1], c[1], r[2], d[2], f[2], c[2], 0, 0, 0, 1]

    def project(self, p: tuple[float, float, float]):
        """(u, v, depth) or None behind the camera."""
        d = (p[0] - self.c[0], p[1] - self.c[1], p[2] - self.c[2])
        z = sum(a * b for a, b in zip(d, self.fwd))
        if z < 0.2:
            return None
        x = sum(a * b for a, b in zip(d, self.right))
        y = sum(a * b for a, b in zip(d, self.down))
        return CAM_F * x / z + CAM_W / 2, CAM_F * y / z + CAM_H / 2, z


def camera_frame(a: Agent, agents: list[Agent], ball: Ball, head_yaw: float) -> bytes:
    from PIL import Image, ImageDraw  # only the camera needs PIL

    cam = FakeCamera(a.x, a.y, a.angle + head_yaw)
    img = Image.new("RGB", (CAM_W, CAM_H), (205, 205, 210))
    draw = ImageDraw.Draw(img)
    horizon = CAM_H / 2 - CAM_F * cam.fwd[2] / cam.down[2]  # rows below it see the ground (no camera roll)
    draw.rectangle([0, max(0, horizon), CAM_W, CAM_H], fill=(52, 120, 60))
    for line in _field_lines():
        pts = []
        for (x0, y0), (x1, y1) in zip(line, line[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.05))
            pts += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]
        uv = [cam.project((x, y, 0.0)) for x, y in pts]
        for p, q in zip(uv, uv[1:]):
            if p and q:
                draw.line([p[:2], q[:2]], fill=(235, 235, 235), width=2)
    det = []

    def box(cls, conf, x, y, half_w, height, color):
        foot, head = cam.project((x, y, 0.0)), cam.project((x, y, height))
        if not foot or not head:
            return
        w = CAM_F * half_w / foot[2]
        b = [foot[0] - w, head[1], foot[0] + w, foot[1]]
        if b[2] < 0 or b[0] > CAM_W or b[3] < 0 or b[1] > CAM_H:
            return
        draw.rectangle(b, fill=color)
        det.append([cls, conf, round(b[0], 1), round(b[1], 1), round(b[2] - b[0], 1), round(b[3] - b[1], 1)])

    for s in (-1, 1):
        for gy in (-1.3, 1.3):
            box("GoalPost", 0.8, s * HW, gy, 0.05, 1.8, (245, 245, 245))
    for o in sorted(agents, key=lambda o: -math.hypot(o.x - a.x, o.y - a.y)):  # far first
        if o is not a:
            box("Robot", 0.85, o.x, o.y, 0.2, 1.2, (40, 40, 48))
    centre = cam.project((ball.x, ball.y, 0.11))
    if centre:
        r = CAM_F * 0.11 / centre[2]
        b = [centre[0] - r, centre[1] - r, centre[0] + r, centre[1] + r]
        draw.ellipse(b, fill=(250, 250, 250), outline=(20, 20, 20))
        if b[2] > 0 and b[0] < CAM_W and b[3] > 0 and b[1] < CAM_H:
            det.append(["Ball", 0.9, round(b[0], 1), round(b[1], 1), round(2 * r, 1), round(2 * r, 1)])
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=70)
    header = {"id": a.id, "team": TEAMS.get(a.color, 0), "color": a.color, "w": CAM_W, "h": CAM_H,
              "K": [CAM_F, CAM_F, CAM_W / 2, CAM_H / 2], "T": [round(v, 5) for v in cam.transform()],
              "det": det, "ts": time.time_ns()}
    return pack_frame(header, out.getvalue())


# The robot-code commit the gateway compares against (its ../spqrbooster2026 checkout), so the fake fleet is "current"
HEAD = subprocess.run(["git", "-C", str(pathlib.Path(__file__).resolve().parents[2] / "spqrbooster2026"), "rev-parse", "--short=8", "HEAD"],
                      capture_output=True, text=True).stdout.strip() or "0f8e451b"

LATCH = {"v": ""}  # like LowControlBridge: "stop" / "damp" from POST /stop, cleared by the Play or Manual combo


def joystick_input() -> None:
    """Thread: the robots' UDP 10007 joystick input, enough for STOP / DAMP / Resume (all fake robots share it)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, 10007))
    except OSError as exc:
        print(f"[udp_sender] no fake STOP: UDP 10007 is busy ({exc})")
        return
    while True:
        try:
            msg = json.loads(sock.recvfrom(4096)[0])
        except ValueError:
            continue
        if msg.get("damp"):
            LATCH["v"] = "damp"
        elif msg.get("lie") and LATCH["v"] != "damp":
            LATCH["v"] = "lie"
        elif msg.get("stop") and (LATCH["v"] not in ("damp", "lie") or (LATCH["v"] == "damp" and msg.get("undamp"))):
            # a STOP keeps a lying robot down; only a one-robot STOP ends a damping
            LATCH["v"] = "stop"
        elif msg.get("rb") and msg.get("rt") and (msg.get("a") or msg.get("b")):  # Play / Manual combo
            LATCH["v"] = ""


def camera_requests(wanted: dict, lock: threading.Lock) -> None:
    """Thread: like DebugCameraSender, stream a robot's camera for 3 s after each request."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((HOST, REQUEST_PORT))
    except OSError as exc:
        print(f"[udp_sender] no fake camera: UDP {REQUEST_PORT} is busy ({exc})")
        return
    while True:
        data, addr = sock.recvfrom(1000)
        try:
            req = json.loads(data)
            with lock:
                wanted[int(req["id"])] = (time.monotonic() + 3.0, (addr[0], int(req.get("port", 10009))))
        except (ValueError, KeyError, TypeError):
            continue


def main() -> None:
    rng = random.Random()
    agents = create_agents(N_AGENTS, HW, HH, speed=1.5, seed=rng.randint(0, 9999))
    ball   = Ball(x=0.0, y=0.0, vx=2.5, vy=1.8, radius=0.11, color="white")
    wanted, lock = {}, threading.Lock()  # robot id -> (stream until, (gateway ip, port))
    threading.Thread(target=camera_requests, args=(wanted, lock), daemon=True).start()
    threading.Thread(target=joystick_input, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    dt = 1.0 / FPS
    t_start = time.monotonic()
    next_frame = 0.0
    print(f"[udp_sender] Sending to {HOST}:{PORT} at {FPS} fps  (Ctrl+C to stop)")
    try:
        while True:
            t0 = time.monotonic()
            for agent in agents:
                if not LATCH["v"]:  # stopped or damped robots stand still
                    agent.step(dt, HW, HH)
            ball.step(dt, HW, HH)

            # Occasionally randomise role/state to show legend updates
            for agent in agents:
                if random.random() < 0.002:
                    agent.state = random.choice(AGENT_STATES)
                if random.random() < 0.001:
                    agent.role = random.choice(AGENT_ROLES)

            for packet in build_packets(agents, ball, t0 - t_start, rng):
                sock.sendto(json.dumps(packet).encode(), (HOST, PORT))

            if t0 >= next_frame:
                next_frame = t0 + 1.0 / CAM_FPS
                with lock:
                    live = {i: target for i, (until, target) in wanted.items() if until > t0}
                for i, a in enumerate(agents):
                    if a.id in live:
                        sock.sendto(camera_frame(a, agents, ball, _fake_joints(i)["AAHead_yaw"]), live[a.id])

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, dt - elapsed))
    except KeyboardInterrupt:
        print("\n[udp_sender] Stopped.")


if __name__ == "__main__":
    main()
