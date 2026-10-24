"""Receive-only reception of robot data from robots on ANY branch, merged per robot with the debug telemetry.

Three sources, all listened to at the same time (config.yaml `reception:`; every switch defaults to on):
  debug  UDP 10006, JSON of DebugMessageSender (src/socket_client.py UDPReceiver): only our oraculum branches. Richest.
  team   UDP 10000 + team number, broadcast, the binary SPQRMessage of TeamMessageSender. Every SPQR branch sends it.
         Two formats, detected per packet (decode_team_message): "rcap" (mappazzone, RCAP2026-DEV) and "main" (main).
         Ports: own_team, both teams of the current GameController packet and reception.teams. Packets that decode in
         neither format (other teams, unknown branches) are counted per team, not decoded.
  gc     UDP 3939, RoboCupGameControlReturnData (32 bytes) that robots send to the GameController's address: it reaches
         this host only when the robots take this host for the GameController (oraculum's simulated referee, or a
         robot's settings.yaml gameController.address).

Nothing here sends a datagram (also in match mode): sockets are bound and read, never written.

Merge (Reception.merge, used by GET /state only): robots are keyed by (sender IP, team, player). Per field the highest
priority source that is fresh (< FRESH_S) wins: debug > team > gc; with no fresh source, the highest one that has it.
Each agent gets `sources` (["debug", "team", "gc"], priority order), `source_age` {source: s} and `readonly`.
A robot with no debug telemetry is read-only (`readonly: true`, `sys.link: "none"`): it is never a command target,
because every command route (/stop, /goto, /control, /camera) reads only the debug receiver.
Frames: team messages and GC return poses are in the robot's own team frame. A robot of the colour
frames.mirror_team_color is point-mirrored like the telemetry. Colour: the GameController's field player colour of its
team, else the colour a debug robot of its team reports, else unknown (`color: ""`, `frame: "team"`, not mirrored).
Self-check: python3 tools/test_reception.py
"""

import math
import select
import socket
import struct
import threading
import time
from collections import deque

from gc_client import GC_RETURN_PORT, parse_gc_return
from socket_client import KEEP_SILENT_S, LINK_WINDOW, mirror_pose

FRESH_S = 3.5  # a source older than this loses its fields to a lower one (the debug receiver's own timeout)
TEAM_PORT_BASE = 10000  # spqrbooster2026 Settings.cpp: teamPort = 10000 + teamNumber
GC_COLOURS = ("blue", "red", "yellow", "black", "white", "green", "orange", "purple", "brown", "gray")  # TEAM_BLUE=0 ...
PRIORITY = ("debug", "team", "gc")
FIELDS = ("x", "y", "angle", "role", "fallen", "ball", "obstacles")

# ---------------------------------------------------------------------------
# SPQRMessage (spqrbooster2026 src/app/utils/communication/SPQRMessage.h, serialized by src/core/include/Serialization.h)
#
# The serializer is an LSB-first BIT stream (Buffers.h BitBuffer): bool = 1 bit, arithmetic types = their little-endian
# bytes, std::vector = 8-bit count + elements, nested IDataObject = uint32 byte count, zero bits up to the next byte,
# then the nested object's own stream. So the fields after `isNTPRequest` are not byte-aligned.
#   rcap (mappazzone, RCAP2026-DEV): u64 senderTimestamp, u8 playerNumber, u8 status, bit isNTPRequest,
#        vector<NTPMessage>, LocalBall, RobotPose, PlayerRole, LocalObstacles   (the last four nested)
#   main:                            u8 playerNumber, u64 senderTimestamp, bit isNTPRequest,
#        vector<NTPMessage>, LocalBall, RobotPose, PlayerRole, GlobalObstacles
# Nested (…ForTheTeamMessage, MAKE_NETWORKABLE field lists):
#   LocalBall  rcap: position, velocity, endPosition (Vector3f), covariance (Matrix3f), seen (bit), lastSeenTime (u64),
#                    lastSeenPosition (Vector3f)                         = 93 bytes
#              main: position, velocity, covariance, seen, lastSeenTime = 69 bytes
#   RobotPose  rcap: pose (x, y, theta: Vector3f), covariance, positionQuality, orientationQuality (u32) = 56 bytes
#              main: pose, covariance                                                                 = 48 bytes
#   PlayerRole int32 Role (the enums differ: ROLES)
#   LocalObstacles  (rcap) centers, velocities (vector<Vector3f>), covariances (vector<Matrix3f>), seenCount (vector<int>),
#                   obstacleTypes (vector<ObjectType int>); robot frame
#   GlobalObstacles (main) localObstacleCenters, localObstacleVelocities, localObstacleCovariances, globalObstacleCenters,
#                   seenCount, obstacleTypes (0 goal post, 1 person, 2 robot); main's sender leaves it empty
# Units: metres, radians. Ball and rcap obstacles are robot-relative; the pose is in the robot's own team frame.
# ---------------------------------------------------------------------------

ROLES = {"rcap": ("Goalie", "Striker", "LeftGuard", "RightGuard", "PassiveStriker", "Dummy"),
         "main": ("Goalie", "Defender", "Striker", "RushGoalie", "Dummy")}
MIN_BALL = {"rcap": 93, "main": 69}  # bytes: a longer nested object (a branch that adds fields at the end) still decodes
MIN_POSE = {"rcap": 56, "main": 48}
STATUS = ("playing", "fallen", "penalized")  # rcap TeammateStatus
RCAP_OBSTACLE = {1: 0, 2: 1, 7: 2}  # ObjectType GoalPost, Person, Opponent -> oraculum's 0 goal post, 1 person, 2 robot


class _Bits:
    """LSB-first bit reader, as BitBuffer::read."""

    def __init__(self, data: bytes) -> None:
        self.data, self.v, self.n, self.o = data, int.from_bytes(data, "little"), len(data) * 8, 0

    def u(self, nbits: int) -> int:
        if self.o + nbits > self.n:
            raise ValueError("underrun")
        x = (self.v >> self.o) & ((1 << nbits) - 1)
        self.o += nbits
        return x

    def i32(self) -> int:
        return struct.unpack("<i", self.u(32).to_bytes(4, "little"))[0]

    def f32(self) -> float:
        return struct.unpack("<f", self.u(32).to_bytes(4, "little"))[0]

    def floats(self, n: int) -> list:
        return [self.f32() for _ in range(n)]

    def blob(self) -> bytes:  # nested IDataObject
        size = self.u(32)
        self.o = (self.o + 7) & ~7
        start = self.o // 8
        if start + size > len(self.data):
            raise ValueError("nested object past the end")
        self.o += size * 8
        return self.data[start:start + size]

    def vector(self, read) -> list:
        return [read() for _ in range(self.u(8))]


class _BitWriter:
    """LSB-first bit writer, as BitBuffer::write (tests and tools/udp_sender.py)."""

    def __init__(self) -> None:
        self.v, self.o = 0, 0

    def u(self, x: int, nbits: int) -> "_BitWriter":
        self.v |= (x & ((1 << nbits) - 1)) << self.o
        self.o += nbits
        return self

    def f32(self, *xs: float) -> "_BitWriter":
        for x in xs:
            self.u(struct.unpack("<I", struct.pack("<f", x))[0], 32)
        return self

    def blob(self, b: bytes) -> "_BitWriter":
        self.u(len(b), 32)
        self.o = (self.o + 7) & ~7
        self.v |= int.from_bytes(b, "little") << self.o
        self.o += len(b) * 8
        return self

    def bytes(self) -> bytes:
        return self.v.to_bytes((self.o + 7) // 8, "little")


def _walk(data: bytes, fmt: str):
    """The top-level stream of one format; raises ValueError unless it ends exactly at the end of the datagram."""
    r = _Bits(data)
    if fmt == "rcap":
        stamp, player, status = r.u(64), r.u(8), r.u(8)
    else:
        player, stamp, status = r.u(8), r.u(64), None
    ntp = bool(r.u(1))
    responses = r.vector(r.blob)
    ball, pose, role, obstacles = r.blob(), r.blob(), r.blob(), r.blob()
    if r.o != r.n:
        raise ValueError("trailing bytes")
    if not 1 <= player <= 20 or (status is not None and status > 2):
        raise ValueError("player or status out of range")
    if len(ball) < MIN_BALL[fmt] or len(pose) < MIN_POSE[fmt] or len(role) < 4 or any(len(x) < 17 for x in responses):
        raise ValueError("nested object too short")
    return stamp, player, status, ntp, ball, pose, role, obstacles


def _obstacles(blob: bytes, fmt: str) -> list:
    """[{x, y, type}]: rcap robot-relative (LocalObstacles), main field frame (GlobalObstacles); [] if it does not parse."""
    try:
        r = _Bits(blob)
        v3 = lambda: r.floats(3)  # noqa: E731
        if fmt == "rcap":
            centers, _, _ = r.vector(v3), r.vector(v3), r.vector(lambda: r.floats(9))
        else:
            r.vector(v3), r.vector(v3), r.vector(lambda: r.floats(9))
            centers = r.vector(v3)
        r.vector(r.i32)  # seenCount
        types = r.vector(r.i32)
    except ValueError:
        return []
    out = []
    for i, c in enumerate(centers):
        t = types[i] if i < len(types) else -1
        t = RCAP_OBSTACLE.get(t, -1) if fmt == "rcap" else (t if t in (0, 1, 2) else -1)
        if all(math.isfinite(v) for v in c[:2]):
            out.append({"x": c[0], "y": c[1], "type": t})
    return out


def decode_team_message(data: bytes):
    """One SPQRMessage datagram of either format, or None. Detection: the datagram must parse as one format's chain of
    fields and nested objects ending exactly at its last byte, with a player number 1..20 and a finite pose.
    Returns {format, player, status, ntp, stamp, x, y, theta, role, ball_local (x, y) | None, obstacles, obstacles_frame}.
    """
    for fmt in ("rcap", "main"):
        try:
            stamp, player, status, ntp, ball, pose, role, obstacles = _walk(data, fmt)
        except ValueError:
            continue
        x, y, theta = _Bits(pose).floats(3)
        if not all(math.isfinite(v) and abs(v) < 100 for v in (x, y, theta)):
            continue
        b = _Bits(ball)
        position = b.floats(3)
        b.floats(3 + (3 if fmt == "rcap" else 0) + 9)  # velocity, [endPosition], covariance
        seen = bool(b.u(1))
        role_id = _Bits(role).i32()
        names = ROLES[fmt]
        return {"format": fmt, "player": player, "status": STATUS[status] if status is not None else "",
                "ntp": ntp, "stamp": stamp, "x": x, "y": y, "theta": theta,
                "role": names[role_id] if 0 <= role_id < len(names) else str(role_id),
                "ball_local": (position[0], position[1]) if seen and all(math.isfinite(v) for v in position[:2]) else None,
                "obstacles": _obstacles(obstacles, fmt), "obstacles_frame": "robot" if fmt == "rcap" else "team"}
    return None


def encode_team_message(fmt: str, player: int, x: float, y: float, theta: float, role: int = 1, status: int = 0,
                        ball_local=None, obstacles=(), stamp: int = 123456, ntp_responses: int = 0, ball_pad: int = 0) -> bytes:
    """An SPQRMessage as the robot's serializer writes it (fmt "rcap" or "main"). Written from the C++ above: it checks
    the decoder against this reading of the serializer, not against the robot's bytes (those: tools/golden/).
    ball_pad: zero bytes after the ball's fields, as a branch that adds a field at the end of LocalBall would send."""
    seen = ball_local is not None
    bx, by = ball_local or (0.0, 0.0)
    ball = _BitWriter().f32(bx, by, 0.1, 0.0, 0.0, 0.0)  # position (z 0.1), velocity
    if fmt == "rcap":
        ball.f32(bx, by, 0.1)  # endPosition
    ball.f32(*([0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01])).u(int(seen), 1).u(stamp, 64)
    if fmt == "rcap":
        ball.f32(bx, by, 0.1)  # lastSeenPosition
    ball.u(0, 8 * ball_pad)
    pose = _BitWriter().f32(x, y, theta).f32(*([0.0] * 9))
    if fmt == "rcap":
        pose.u(4, 32).u(4, 32)  # positionQuality, orientationQuality: Good
    obs = _BitWriter()
    n = len(obstacles)
    if fmt == "rcap":  # robot frame: obstacles are (x, y, type ObjectType)
        obs.u(n, 8).f32(*[v for o in obstacles for v in (o[0], o[1], 0.0)])
        obs.u(n, 8).f32(*([0.0] * 3 * n)).u(n, 8).f32(*([0.0] * 9 * n))
    else:  # local centers, velocities, covariances (none), then global centers
        obs.u(0, 8).u(0, 8).u(0, 8).u(n, 8).f32(*[v for o in obstacles for v in (o[0], o[1], 0.0)])
    obs.u(n, 8)
    for _ in obstacles:
        obs.u(5, 32)  # seenCount
    obs.u(n, 8)
    for o in obstacles:
        obs.u(o[2] & 0xFFFFFFFF, 32)
    w = _BitWriter()
    if fmt == "rcap":
        w.u(stamp, 64).u(player, 8).u(status, 8)
    else:
        w.u(player, 8).u(stamp, 64)
    w.u(1, 1).u(ntp_responses, 8)  # isNTPRequest
    for i in range(ntp_responses):
        w.blob(_BitWriter().u(i + 1, 8).u(stamp - 50, 64).u(stamp - 40, 64).bytes())
    return w.blob(ball.bytes()).blob(pose.bytes()).blob(_BitWriter().u(role, 32).bytes()).blob(obs.bytes()).bytes()


def _to_team_frame(x: float, y: float, theta: float, lx: float, ly: float) -> dict:
    """A robot-relative point (metres) in the robot's own team frame."""
    c, s = math.cos(theta), math.sin(theta)
    return {"x": x + c * lx - s * ly, "y": y + s * lx + c * ly}


def team_info(msg: dict) -> dict:
    """The agent fields of a decoded team message, in the robot's own team frame (not yet mirrored)."""
    x, y, t = msg["x"], msg["y"], msg["theta"]
    obstacles = msg["obstacles"]
    if msg["obstacles_frame"] == "robot":
        obstacles = [{**_to_team_frame(x, y, t, o["x"], o["y"]), "type": o["type"]} for o in obstacles]
    return {"x": x, "y": y, "angle": t, "role": msg["role"], "fallen": msg["status"] == "fallen",
            "penalized": msg["status"] == "penalized", "format": msg["format"],
            "ball": _to_team_frame(x, y, t, *msg["ball_local"]) if msg["ball_local"] else None, "obstacles": obstacles}


def gc_info(ret: dict) -> dict:
    """The agent fields of a parsed GC return packet (mm -> m), in the robot's own team frame. The ball counts as seen
    when the robot saw it in the last 3 s (ponytail: fixed age limit; the debug ball has no age either)."""
    x, y, t = ret["pose"]
    x, y = x / 1000, y / 1000
    bx, by = ret["ball"]
    seen = 0 <= ret["ball_age"] < 3
    return {"x": x, "y": y, "angle": t, "fallen": ret["fallen"] == 1,
            "ball": _to_team_frame(x, y, t, bx / 1000, by / 1000) if seen else None}


def _mirrored(info: dict) -> dict:
    out = dict(info)
    out["x"], out["y"], out["angle"] = mirror_pose(info["x"], info["y"], info["angle"])
    if info.get("ball"):
        out["ball"] = {"x": -info["ball"]["x"], "y": -info["ball"]["y"]}
    if info.get("obstacles"):
        out["obstacles"] = [{**o, "x": -o["x"], "y": -o["y"]} for o in info["obstacles"]]
    return out


# ---------------------------------------------------------------------------
# Receiver + merge
# ---------------------------------------------------------------------------

class Reception:
    """Team-message and GC-return receiver (one thread, select over its sockets) and the per-robot merge for /state.

    teams_fn() -> team numbers of the current GameController packet; skip_ports: ports the gateway itself uses (team
    numbers 6-9 would give 10006-10009: those ports are not shared, their unicast would be split between two sockets).
    """

    def __init__(self, own_team: int = 0, teams=(), team_messages: bool = True, gc_return: bool = True,
                 mirror_color: str = "blue", teams_fn=lambda: [], skip_ports=(), host: str = "0.0.0.0",
                 port_base: int = TEAM_PORT_BASE, gc_return_port: int = GC_RETURN_PORT) -> None:
        self.own_team, self.extra_teams = own_team, [int(t) for t in teams or []]
        self.team_on, self.gc_on = team_messages, gc_return
        self.mirror_color = (mirror_color or "").lower()
        self.teams_fn, self.skip_ports, self.host = teams_fn, set(skip_ports), host
        self.port_base, self.gc_return_port = port_base, gc_return_port
        self._records = {}  # (ip, team, player) -> {source: (time, info)}
        self._link = {}  # sender IP -> deque of (time, bytes) of the last LINK_WINDOW s; and the last time below
        self._last = {}
        self.teams = {}  # team -> {port, packets, bytes, decoded, unknown, formats, senders, listening, error}
        self.gc_return = {"port": gc_return_port, "packets": 0, "invalid": 0, "listening": False, "error": "" if gc_return else "off"}
        self._socks = {}  # socket -> team number, or "gc"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="Reception")

    # -- sockets (receive only) ---------------------------------------------
    def start(self) -> None:
        if self.gc_on:
            # The GameController binds 3939 with no reuse flag (game_controller_net status_message_receiver.rs), and a
            # unicast port shared with SO_REUSEPORT is load-balanced: so a plain bind, once. If the GameController runs
            # on this host and started first, this fails and the source stays off; started after us, IT would fail.
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.bind((self.host, self.gc_return_port))
                self._socks[s] = "gc"
                self.gc_return["listening"] = True
            except OSError as exc:
                self.gc_return["error"] = f"{exc.strerror or exc}: a GameController on this host?"
                print(f"[Reception] GC return port {self.gc_return_port} not bound ({exc}); that source is off")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def wanted_teams(self) -> set:
        try:
            gc_teams = [int(t) for t in self.teams_fn() or []]
        except Exception:  # noqa: BLE001 - a broken GameController packet must not stop reception
            gc_teams = []
        return {t for t in [self.own_team, *self.extra_teams, *gc_teams] if t and 0 < t < 256}

    def _open_team_ports(self) -> None:
        for team in self.wanted_teams() - set(self.teams):
            port = self.port_base + team
            entry = {"port": port, "packets": 0, "bytes": 0, "decoded": 0, "unknown": 0, "formats": {}, "senders": set(),
                     "listening": False, "error": ""}
            self.teams[team] = entry
            if port in self.skip_ports:
                entry["error"] = f"port {port} is one of the gateway's own ports"
                print(f"[Reception] team {team}: port {port} is a gateway port, not listened to")
                continue
            try:  # broadcast: every socket bound with SO_REUSEADDR (+ SO_REUSEPORT) gets its own copy, as the robots' own
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                s.bind((self.host, port))
                self._socks[s] = team
                entry["listening"] = True
                print(f"[Reception] team {team}: listening on {self.host}:{port}")
            except OSError as exc:
                entry["error"] = str(exc.strerror or exc)
                print(f"[Reception] team {team}: port {port} not bound ({exc})")

    def _run(self) -> None:
        next_check = 0.0
        try:
            while not self._stop.is_set():
                if self.team_on and time.time() >= next_check:
                    self._open_team_ports()  # new GameController teams get their port within 1 s
                    next_check = time.time() + 1.0
                if not self._socks:
                    self._stop.wait(0.5)
                    continue
                ready, _, _ = select.select(list(self._socks), [], [], 0.5)
                for s in ready:
                    try:
                        data, addr = s.recvfrom(65535)
                    except OSError:
                        continue
                    which = self._socks[s]
                    if which == "gc":
                        self.handle_gc_return(addr[0], data)
                    else:
                        self.handle_team(which, addr[0], data)
        finally:
            for s in self._socks:
                s.close()

    # -- packets -------------------------------------------------------------
    def _count_link(self, ip: str, n: int, now: float) -> None:
        self._link.setdefault(ip, deque()).append((now, n))
        self._last[ip] = now

    def handle_team(self, team: int, ip: str, data: bytes, now: float = None) -> bool:
        """One datagram from the port of `team`: decoded into that robot's record, or counted as unknown."""
        now = time.time() if now is None else now
        msg = decode_team_message(data)
        with self._lock:
            entry = self.teams.setdefault(team, {"port": self.port_base + team, "packets": 0, "bytes": 0, "decoded": 0,
                                                 "unknown": 0, "formats": {}, "senders": set(), "listening": False, "error": ""})
            entry["packets"] += 1
            entry["bytes"] += len(data)
            entry["senders"].add(ip)
            if msg is None:
                entry["unknown"] += 1
                return False
            entry["decoded"] += 1
            entry["formats"][msg["format"]] = entry["formats"].get(msg["format"], 0) + 1
            self._records.setdefault((ip, team, msg["player"]), {})["team"] = (now, team_info(msg))
            self._count_link(ip, len(data), now)
        return True

    def handle_gc_return(self, ip: str, data: bytes, now: float = None) -> bool:
        now = time.time() if now is None else now
        ret = parse_gc_return(data)
        with self._lock:
            if ret is None:
                self.gc_return["invalid"] += 1
                return False
            self.gc_return["packets"] += 1
            self._records.setdefault((ip, ret["team"], ret["player"]), {})["gc"] = (now, gc_info(ret))
            self._count_link(ip, len(data), now)
        return True

    # -- /state --------------------------------------------------------------
    def status(self) -> dict:
        """/state `reception`: per team its port and packet counts (decoded, unknown format: the network budget view)."""
        with self._lock:
            teams = {str(t): {**e, "senders": len(e["senders"])} for t, e in sorted(self.teams.items())}
            return {"team_messages": self.team_on, "teams": teams, "gc_return": dict(self.gc_return)}

    def link_stats(self, now: float = None) -> dict:
        """{ip: {hz, kbps, age}} of the team-message and GC-return packets, as UDPReceiver.link_stats."""
        now = time.time() if now is None else now
        with self._lock:
            out = {}
            for ip, q in self._link.items():
                while q and now - q[0][0] > LINK_WINDOW:
                    q.popleft()
                out[ip] = {"hz": round(len(q) / LINK_WINDOW, 1), "kbps": round(sum(n for _, n in q) * 8 / 1000 / LINK_WINDOW, 1),
                           "age": round(now - self._last.get(ip, 0.0), 2)}
            return out

    def merge(self, agents: list, link: dict, gc_colours: dict = None, now: float = None) -> list:
        """The agents of /state: the debug agents (dicts of UDPReceiver.latest()) with the team and GC-return data of the
        same robot merged in, plus one read-only agent per robot seen only by team message or GC return.
        link: the debug receiver's link_stats (its age is the debug source age). gc_colours: {team: colour name}."""
        now = time.time() if now is None else now
        gc_colours = gc_colours or {}
        with self._lock:
            for key in [k for k, rec in self._records.items() if all(now - t >= KEEP_SILENT_S for t, _ in rec.values())]:
                del self._records[key]
            records = {k: {s: v for s, v in rec.items() if now - v[0] < KEEP_SILENT_S} for k, rec in self._records.items()}
        team_colour = {**{a.get("team"): a.get("color") for a in agents if a.get("team") and a.get("color")}, **gc_colours}
        out, used = [], set()
        for a in agents:
            key = (a.get("ip") or "127.0.0.1", a.get("team"), a.get("id"))
            if key not in records and not a.get("team"):  # an old sender without a team number: match on IP and number
                key = next((k for k in records if k[0] == key[0] and k[2] == key[2]), key)
            used.add(key)
            debug_age = (link.get(key[0]) or {}).get("age", 0.0)
            out.append(self._merged(dict(a), debug_age, records.get(key, {}), str(a.get("color") or ""), now))
        for key, rec in records.items():
            if key in used or not rec:
                continue
            ip, team, player = key
            colour = str(team_colour.get(team) or "")
            base = {"id": player, "team": team, "ip": ip, "x": 0.0, "y": 0.0, "angle": 0.0, "role": "", "state": "",
                    "color": colour, "joints": {}, "battery": -1.0, "fallen": False, "latch": "", "goto": None, "robot": "",
                    "ball": None, "obstacles": [], "sys": {"link": "none"}}
            if not colour:
                base["frame"] = "team"  # colour unknown: its own team frame, not mirrored
            agent = self._merged(base, None, rec, colour, now)
            if any(info.get("penalized") for _, info in rec.values()):
                agent["state"] = "P"
            out.append(agent)
        return out

    def _merged(self, agent: dict, debug_age, rec: dict, colour: str, now: float) -> dict:
        mirror = bool(self.mirror_color) and colour.lower() == self.mirror_color
        srcs = [] if debug_age is None else [("debug", debug_age, agent)]
        for name in PRIORITY[1:]:
            if name in rec:
                t, info = rec[name]
                srcs.append((name, now - t, _mirrored(info) if mirror else info))
        for f in FIELDS:  # the highest fresh source; with none fresh, the highest that has the field
            pick = next((d[f] for _, age, d in srcs if age < FRESH_S and d.get(f) is not None), None)
            if pick is None:
                pick = next((d[f] for _, _, d in srcs if d.get(f) is not None), None)
            if pick is not None or f == "ball":
                agent[f] = pick
        if "team" in rec:
            agent["team_format"] = rec["team"][1]["format"]
        agent["sources"] = [name for name, _, _ in srcs]
        agent["source_age"] = {name: round(age, 1) for name, age, _ in srcs}
        agent["readonly"] = debug_age is None
        return agent
