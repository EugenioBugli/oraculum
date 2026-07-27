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
import re
import time
import queue
import socket
import threading
from dataclasses import dataclass, field
from typing import Optional, TypeVar, Type

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

T = TypeVar("T")


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


@dataclass
class TextMsg:
    path: str
    text: str
    agent_id: int = 0


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
        return cls(agents=agents, ball=ball, drawings=drawings, texts=texts)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# UDP receiver — runs in a background thread
# ---------------------------------------------------------------------------

class UDPReceiver:
    """Bind to (host, port) and receive GameStateMsg packets in a daemon thread.
    Merges agent telemetry packets from multiple sources by agent ID.
    """

    def __init__(self, host: str, port: int) -> None:
        self._addr = (host, port)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="UDPReceiver")
        
        # Thread-safe telemetry cache
        self._cached_agents = {}
        self._cached_ball = None
        self._cached_drawings = {}
        self._cached_texts = {}
        self._last_update_times = {}  # maps sender IP to last packet timestamp
        self._last_ball_update_time = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> Optional[GameStateMsg]:
        """Return the merged latest game state, or None if no data received yet."""
        with self._lock:
            now = time.time()
            timeout_duration = 2.0
            
            # Identify active IPs
            active_ips = {ip for ip, t in self._last_update_times.items() if now - t < timeout_duration}
            
            # Prune agents
            stale_agents = [key for key in self._cached_agents.keys() if key[0] not in active_ips]
            for key in stale_agents:
                del self._cached_agents[key]
                
            # Prune drawings/texts from inactive agents
            active_agent_ids = {agent.id for agent in self._cached_agents.values()}
            
            stale_drawings = [key for key in self._cached_drawings.keys() if key[0] not in active_agent_ids]
            for key in stale_drawings:
                del self._cached_drawings[key]
                
            stale_texts = [key for key in self._cached_texts.keys() if key[0] not in active_agent_ids]
            for key in stale_texts:
                del self._cached_texts[key]
                
            # Prune ball
            if self._cached_ball is not None and now - self._last_ball_update_time > timeout_duration:
                self._cached_ball = None

            if not self._cached_agents and self._cached_ball is None and not self._cached_drawings and not self._cached_texts:
                return None
            return GameStateMsg(
                agents=list(self._cached_agents.values()),
                ball=self._cached_ball,
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

                with self._lock:
                    now = time.time()
                    self._last_update_times[addr[0]] = now
                    
                    sender_id = msg.agents[0].id if msg.agents else 0
                    for agent in msg.agents:
                        agent.ip = addr[0]
                        self._cached_agents[(addr[0], agent.id)] = agent
                    if msg.ball is not None:
                        self._cached_ball = msg.ball
                        self._last_ball_update_time = now
                    for drawing in msg.drawings:
                        drawing.agent_id = sender_id
                        self._cached_drawings[(sender_id, drawing.path)] = drawing
                    for t in msg.texts:
                        t.agent_id = sender_id
                        self._cached_texts[(sender_id, t.path)] = t
        finally:
            sock.close()
            print("[UDPReceiver] Socket closed.")
