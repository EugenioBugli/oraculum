"""UDP socket client with a dataclass-based message schema.

To change the message format, edit the dataclasses in the SCHEMA section only.
Rules for safe evolution:
  - New fields MUST have a default value so old senders still work.
  - Unknown fields from the network are silently ignored so old receivers
    still work when the sender adds fields.
  - Removing a field: add a default first, deploy receivers, then remove.
"""

import dataclasses
import json
import math
import re
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Type, TypeVar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T = TypeVar("T")
LINK_WINDOW = 2.0  # seconds of packets that link_stats() averages over
KEEP_SILENT_S = 10.0  # a silent sender's robots stay in /state (greyed on the pages) this long


def _from_dict(cls: Type[T], d: dict) -> T:
    """Instantiate a dataclass from a dict, ignoring unknown keys."""
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# SCHEMA — edit this section to change the message format
# ---------------------------------------------------------------------------

@dataclass
class AgentMsg:
    id: int
    x: float
    y: float
    angle: float = 0.0      # heading in radians
    role: str = "M"         # G(oalkeeper) D(efender) M(idfielder) A(ttacker)
    state: str = "R"        # I(dle) R(unning) S(topped) P(enalty) X(error)
    color: str = "#822433"
    ip: str = ""
    # Joint angles in rad, keyed by MJCF joint name of the robot model (e.g. "AAHead_yaw").
    # The WASM 3D view poses the robot with them; missing joints stay at 0.
    joints: dict[str, float] = field(default_factory=dict)
    team: int = 0           # team number (GameController)
    battery: float = -1.0   # percent; -1 = unknown
    fallen: bool = False
    latch: str = ""         # the robot's oraculum latch: "stop", "lie", "damp" (POST /stop) or "" (none)
    robot: str = ""         # model (deploy.yaml robot): "t2", "t1", "k1"; the 3D views draw that model, else (or "") a T2
    # This robot's own beliefs, field frame: its ball estimate {x, y} (None = not seen) and the
    # obstacles it sees [{x, y, type}] (type 0 goal post, 1 person, 2 robot). A one-agent packet's
    # top-level "ball" / "obstacles" (DebugMessageSender) are copied here by GameStateMsg.from_dict.
    ball: Optional[dict] = None
    obstacles: list[dict] = field(default_factory=list)
    # Fleet data: version, cpu (%), load (1 min), temp (deg C), tx / rx (kbit/s, Wi-Fi), rec (bool)
    sys: dict = field(default_factory=dict)


@dataclass
class BallMsg:
    x: float
    y: float


@dataclass
class DrawingMsg:
    type: str  # "point", "circle", "line", "box", "arc"
    path: str
    coords: list[float] = field(default_factory=list)
    color: list[int] = field(default_factory=list)
    size: float = 0.01
    agent_id: int = 0
    frame: str = "field"       # "field" or "viewport"
    condition: str = ""        # condition expression (e.g. role/state)
    ip: str = ""               # sender IP, set by the gateway: two teams can both have a robot 3


@dataclass
class TextMsg:
    path: str
    text: str
    agent_id: int = 0
    ip: str = ""               # sender IP, set by the gateway: two teams can both have a robot 3


@dataclass
class GameStateMsg:
    agents: list[AgentMsg] = field(default_factory=list)
    ball: Optional[BallMsg] = None
    drawings: list[DrawingMsg] = field(default_factory=list)
    texts: list[TextMsg] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "GameStateMsg":
        agents = [_from_dict(AgentMsg, a) for a in d.get("agents", [])]
        ball_data = d.get("ball")
        ball = _from_dict(BallMsg, ball_data) if ball_data else None
        drawings = [_from_dict(DrawingMsg, dr) for dr in d.get("drawings", [])]
        texts = [_from_dict(TextMsg, t) for t in d.get("texts", [])]
        for a in agents:  # nan/inf arrive as null: -1 is "unknown" for every page and the event log
            a.battery = float(a.battery) if isinstance(a.battery, (int, float)) and math.isfinite(a.battery) else -1.0
        if len(agents) == 1:  # one robot per packet: the packet's ball and obstacles are its own beliefs
            a = agents[0]
            if a.ball is None and isinstance(ball_data, dict) and "x" in ball_data and "y" in ball_data:
                a.ball = {"x": ball_data["x"], "y": ball_data["y"]}
            if not a.obstacles and isinstance(d.get("obstacles"), list):
                a.obstacles = d["obstacles"]
        return cls(agents=agents, ball=ball, drawings=drawings, texts=texts)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# UDP receiver — runs in a background thread
# ---------------------------------------------------------------------------

def mirror_packet(msg: "GameStateMsg") -> None:
    """Point-mirror a packet from a team's own frame into the shared field frame, in place.

    Robots localize in their own team's frame (own goal at -x, as the spqrbooster2026 formations); the
    team that defends +x in circus's world frame (blue) is therefore turned by 180 degrees about the
    centre: x, y -> -x, -y and angle -> angle + pi. Drawings in the field frame turn with it.
    """
    for a in msg.agents:
        a.x, a.y = -a.x, -a.y
        a.angle = (a.angle + 2 * math.pi) % (2 * math.pi) - math.pi  # angle + pi, wrapped to [-pi, pi)
        for p in ([a.ball] if a.ball else []) + a.obstacles:
            if isinstance(p, dict) and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float)):
                p["x"], p["y"] = -p["x"], -p["y"]
    if msg.ball is not None:
        msg.ball.x, msg.ball.y = -msg.ball.x, -msg.ball.y
    for d in msg.drawings:
        if d.frame != "field" or len(d.coords) < 2:
            continue
        c = list(d.coords)
        n = 4 if d.type == "line" else 2  # line [x1, y1, x2, y2]; point/circle/box/arc start with [x, y]
        c[:n] = [-v for v in c[:n]]
        if d.type == "arc" and len(c) >= 5:  # arc [x, y, r, start_deg, end_deg]
            c[3], c[4] = c[3] + 180.0, c[4] + 180.0
        d.coords = c


def team_ball(agents) -> Optional[BallMsg]:
    """The ball estimate of the robot nearest to its own estimate (a near robot sees the ball best), or None.

    ponytail: nearest-estimate heuristic; average the estimates with their ages if robots ever send them.
    """
    best = None
    for a in agents:
        b = a.ball if isinstance(a.ball, dict) else None
        if b and all(isinstance(b.get(k), (int, float)) and math.isfinite(b[k]) for k in ("x", "y")):
            d = math.hypot(b["x"] - a.x, b["y"] - a.y)
            if best is None or d < best[0]:
                best = (d, b)
    return BallMsg(x=best[1]["x"], y=best[1]["y"]) if best else None


class UDPReceiver:
    """Bind to (host, port) and receive GameStateMsg packets in a daemon thread.
    Merges agent telemetry packets from multiple sources by agent ID.
    """

    def __init__(self, host: str, port: int, mirror_color: str = "blue") -> None:
        self._addr = (host, port)
        # Packets whose agents report this team colour are point-mirrored (mirror_packet); "" = none.
        self._mirror_color = (mirror_color or "").lower()
        self.mirror_color = self._mirror_color
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="UDPReceiver")
        
        # Thread-safe telemetry cache
        self._cached_agents = {}
        self._agent_times = {}  # (sender IP, agent id) -> last time this agent was reported
        self._cached_ball = None
        self._cached_drawings = {}
        self._cached_texts = {}
        self._last_update_times = {}  # maps sender IP to last packet timestamp
        self._last_ball_update_time = 0.0
        self._link = {}  # sender IP -> deque of (time, bytes) of the last LINK_WINDOW seconds
        self.recorder = None  # session.Recorder; gets every telemetry packet while a recording runs
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def link_stats(self) -> dict:
        """Per sender IP, as the gateway receives it: packets/s, kbit/s and seconds since the last packet."""
        with self._lock:
            now = time.time()
            out = {}
            for ip, q in self._link.items():
                while q and now - q[0][0] > LINK_WINDOW:
                    q.popleft()
                last = self._last_update_times.get(ip, 0.0)
                out[ip] = {"hz": round(len(q) / LINK_WINDOW, 1),
                           "kbps": round(sum(n for _, n in q) * 8 / 1000 / LINK_WINDOW, 1),
                           "age": round(now - last, 2)}
            return out

    def latest(self) -> Optional[GameStateMsg]:
        """Return the merged latest game state, or None if no data received yet."""
        with self._lock:
            now = time.time()
            timeout_duration = 3.5  # robots in oraculum: match send 1 packet/s: one lost packet must not drop them

            # Senders heard in the last 3.5 s are active. A silent sender's robots stay KEEP_SILENT_S in /state, so the
            # pages show them greyed ("LINK N s old", fleet.link[ip].age keeps growing) for a whole Wi-Fi gap.
            active_ips = {ip for ip, t in self._last_update_times.items() if now - t < timeout_duration}
            known_ips = {ip for ip, t in self._last_update_times.items() if now - t < KEEP_SILENT_S}

            # Prune agents: the sender is silent for KEEP_SILENT_S, OR it is active and no longer reports this agent.
            stale_agents = [key for key in self._cached_agents.keys()
                            if key[0] not in known_ips
                            or (key[0] in active_ips and now - self._agent_times.get(key, 0) >= timeout_duration)]
            for key in stale_agents:
                del self._cached_agents[key]
                self._agent_times.pop(key, None)

            # Drawings, texts and the team ball come only from robots of active senders (old drawings are not greyed)
            fresh = {key: a for key, a in self._cached_agents.items() if key[0] in active_ips}

            stale_drawings = [key for key in self._cached_drawings.keys() if key[:2] not in fresh]
            for key in stale_drawings:
                del self._cached_drawings[key]

            stale_texts = [key for key in self._cached_texts.keys() if key[:2] not in fresh]
            for key in stale_texts:
                del self._cached_texts[key]

            # Prune ball
            if self._cached_ball is not None and now - self._last_ball_update_time > timeout_duration:
                self._cached_ball = None

            if not self._cached_agents and self._cached_ball is None and not self._cached_drawings and not self._cached_texts:
                return None
            return GameStateMsg(
                agents=list(self._cached_agents.values()),
                ball=self._cached_ball or team_ball(fresh.values()),
                drawings=list(self._cached_drawings.values()),
                texts=list(self._cached_texts.values())
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(self._addr)
        print(f"[UDPReceiver] Listening on {self._addr[0]}:{self._addr[1]}")

        try:
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                try:
                    # Sanitize invalid numeric floats like -nan, nan, inf, -inf into null before parsing
                    raw_str = data.decode(errors='replace')
                    sanitized_str = re.sub(r'([:,\[])\s*(-?nan|-?inf|-?infinity)\b', r'\1null', raw_str, flags=re.IGNORECASE)
                    
                    # Use strict=False to tolerate raw newlines and control characters in JSON strings
                    msg = GameStateMsg.from_dict(json.loads(sanitized_str, strict=False))
                except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                    payload = data.decode(errors='replace')
                    snippet = payload[max(0, 124-30):124+30]
                    print(f"[UDPReceiver] Malformed packet from {addr}: {exc}")
                    print(f"  Snippet near char 124: ... {repr(snippet)} ...")
                    print(f"  Full payload: {repr(payload)}")
                    continue

                recorder = self.recorder
                if recorder is not None:
                    recorder.write_telemetry(addr[0], sanitized_str)

                if self._mirror_color and any(str(a.color).lower() == self._mirror_color for a in msg.agents):
                    mirror_packet(msg)

                with self._lock:
                    now = time.time()
                    self._last_update_times[addr[0]] = now
                    self._link.setdefault(addr[0], deque()).append((now, len(data)))
                    
                    sender_id = msg.agents[0].id if msg.agents else 0
                    for agent in msg.agents:
                        agent.ip = addr[0]
                        self._cached_agents[(addr[0], agent.id)] = agent
                        self._agent_times[(addr[0], agent.id)] = now
                    # A one-robot packet's ball is that robot's own estimate (agent.ball), not the team ball:
                    # latest() derives the team ball from all estimates.
                    if msg.ball is not None and len(msg.agents) != 1:
                        self._cached_ball = msg.ball
                        self._last_ball_update_time = now
                    for drawing in msg.drawings:
                        drawing.agent_id, drawing.ip = sender_id, addr[0]
                        self._cached_drawings[(addr[0], sender_id, drawing.path)] = drawing
                    for t in msg.texts:
                        t.agent_id, t.ip = sender_id, addr[0]
                        self._cached_texts[(addr[0], sender_id, t.path)] = t
        finally:
            sock.close()
            print("[UDPReceiver] Socket closed.")
