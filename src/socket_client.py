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


@dataclass
class BallMsg:
    x: float
    y: float


@dataclass
class GameStateMsg:
    agents: list[AgentMsg] = field(default_factory=list)
    ball: Optional[BallMsg] = None

    @classmethod
    def from_dict(cls, d: dict) -> "GameStateMsg":
        agents = [_from_dict(AgentMsg, a) for a in d.get("agents", [])]
        ball_data = d.get("ball")
        ball = _from_dict(BallMsg, ball_data) if ball_data else None
        return cls(agents=agents, ball=ball)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# UDP receiver — runs in a background thread
# ---------------------------------------------------------------------------

class UDPReceiver:
    """Bind to (host, port) and receive GameStateMsg packets in a daemon thread.

    Usage::

        receiver = UDPReceiver("0.0.0.0", 10006)
        receiver.start()

        # inside the animation loop:
        msg = receiver.latest()
        if msg is not None:
            ...

        receiver.stop()
    """

    def __init__(self, host: str, port: int, queue_size: int = 10) -> None:
        self._addr = (host, port)
        self._queue: queue.Queue[GameStateMsg] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="UDPReceiver")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> Optional[GameStateMsg]:
        """Drain the queue and return the most recent message, or None."""
        msg = None
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
        return msg

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
                    msg = GameStateMsg.from_dict(json.loads(data.decode()))
                except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                    print(f"[UDPReceiver] Malformed packet from {addr}: {exc}")
                    continue

                # Drop oldest if queue is full so latest data is always fresh
                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                self._queue.put_nowait(msg)
        finally:
            sock.close()
            print("[UDPReceiver] Socket closed.")
