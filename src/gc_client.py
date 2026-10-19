"""GameController UDP receiver and return-message sender.

The GameController broadcasts RoboCupGameControlData on UDP port 3838
(version 20 = HSL GameController, 158 bytes; version 19 = older GameController, 198 bytes).
Robots reply with RoboCupGameControlReturnData (32 bytes) on port 3939.

Quick start::

    from src.gc_client import GCReceiver

    receiver = GCReceiver(own_team=42)
    receiver.start()

    # inside a loop:
    gc = receiver.latest()
    if gc is not None:
        print(gc.state_name, gc.teams[gc.own_team_index].score)

    receiver.stop()
"""

import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants  (mirror RoboCupGameControlData.h)
# ---------------------------------------------------------------------------

GC_DATA_PORT   = 3838
GC_RETURN_PORT = 3939

_GC_HEADER        = b"RGme"
_GC_RETURN_HEADER = b"RGrt"
_GC_RETURN_VER    = 4

MAX_NUM_PLAYERS = 20

# Game states
STATE_INITIAL  = 0
STATE_READY    = 1
STATE_SET      = 2
STATE_PLAYING  = 3
STATE_FINISHED = 4

STATE_NAMES = {0: "INITIAL", 1: "READY", 2: "SET", 3: "PLAYING", 4: "FINISHED"}

# Game phases
GAME_PHASE_NORMAL            = 0
GAME_PHASE_PENALTY_SHOOT_OUT = 1
GAME_PHASE_EXTRA_TIME        = 2
GAME_PHASE_TIMEOUT           = 3

PHASE_NAMES = {0: "NORMAL", 1: "PENALTY_SHOOT_OUT", 2: "EXTRA_TIME", 3: "TIMEOUT"}

# Set plays
SET_PLAY_NONE             = 0
SET_PLAY_DIRECT_FREE_KICK = 1
SET_PLAY_INDIRECT_FREE_KICK = 2
SET_PLAY_PENALTY_KICK     = 3
SET_PLAY_THROW_IN         = 4
SET_PLAY_GOAL_KICK        = 5
SET_PLAY_CORNER_KICK      = 6
SET_PLAY_NAMES = {0: "", 1: "DIRECT FREE KICK", 2: "INDIRECT FREE KICK", 3: "PENALTY KICK", 4: "THROW-IN", 5: "GOAL KICK",
                  6: "CORNER KICK"}

# Penalties (as spqrbooster2026's RoboCupGameControlData.h)
PENALTY_NAMES = {0: "", 1: "Illegal positioning", 2: "Motion in Set", 3: "Motion in Stop", 4: "Local game stuck",
                 5: "Incapable robot", 6: "Pick-up", 7: "Ball holding", 8: "Leaving the field", 9: "Playing with arms/hands",
                 10: "Pushing", 11: "Cautioned", 12: "Sent off", 13: "Substitute"}

# ---------------------------------------------------------------------------
# Binary struct formats  (little-endian, matching x86 GameController output)
#
# RoboCupGameControlData layout:
#   header[4]           4s
#   version..kickingTeam  10B  (10 uint8 fields)
#   secsRemaining         h    (int16)
#   secondaryTime         h    (int16)
#   teams[2]:  each TeamInfo = 6B + 2H + 20*RobotInfo
#   RobotInfo  v20 (158 bytes total): penalty, secsTillUnpenalised, cautions            = 3B
#              v19 (198 bytes total): penalty, secsTillUnpenalised, warnings, cautions  = 4B
#
# RoboCupGameControlReturnData layout (32 bytes):
#   header[4]  4s
#   version+playerNum+teamNum+fallen  4B
#   pose[3]+ballAge+ball[2]           6f
# ---------------------------------------------------------------------------

def _gc_data_struct(robot_info_len: int) -> struct.Struct:
    return struct.Struct("<4s10Bhh" + ("6B2H" + f"{robot_info_len}B" * MAX_NUM_PLAYERS) * 2)

# version -> (struct, bytes per RobotInfo)
_GC_DATA_STRUCTS = {20: (_gc_data_struct(3), 3), 19: (_gc_data_struct(4), 4)}
assert _GC_DATA_STRUCTS[20][0].size == 158, f"Unexpected GC v20 size: {_GC_DATA_STRUCTS[20][0].size}"
assert _GC_DATA_STRUCTS[19][0].size == 198, f"Unexpected GC v19 size: {_GC_DATA_STRUCTS[19][0].size}"

_GC_RETURN_FMT = "<4s4B6f"
_GC_RETURN_STRUCT = struct.Struct(_GC_RETURN_FMT)
assert _GC_RETURN_STRUCT.size == 32, f"Unexpected GC return struct size: {_GC_RETURN_STRUCT.size}"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RobotInfo:
    penalty: int = 0
    secs_till_unpenalised: int = 0
    warnings: int = 0
    cautions: int = 0


@dataclass
class TeamInfo:
    team_number: int = 0
    field_player_colour: int = 0
    goalkeeper_colour: int = 0
    goalkeeper: int = 0
    score: int = 0
    penalty_shot: int = 0
    single_shots: int = 0
    message_budget: int = 0
    players: list[RobotInfo] = field(default_factory=list)


@dataclass
class GameControllerData:
    version: int = 0
    packet_number: int = 0
    players_per_team: int = 0
    competition_type: int = 0
    stopped: bool = False
    game_phase: int = 0
    state: int = 0
    set_play: int = 0
    first_half: bool = True
    kicking_team: int = 0
    secs_remaining: int = 0
    secondary_time: int = 0
    teams: list[TeamInfo] = field(default_factory=list)
    own_team_index: int = -1   # index into teams[] for our team; -1 if unknown

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, str(self.state))

    @property
    def phase_name(self) -> str:
        return PHASE_NAMES.get(self.game_phase, str(self.game_phase))

# ---------------------------------------------------------------------------
# Packet parsing
# ---------------------------------------------------------------------------

def parse_gc_packet(data: bytes, own_team: Optional[int] = None) -> Optional[GameControllerData]:
    """Parse a raw UDP datagram into GameControllerData.

    Returns None if the packet is the wrong size, has an unexpected header, or
    has an unexpected version number.

    If *own_team* is provided, sets GameControllerData.own_team_index to the
    index of that team in teams[], or leaves it as -1 if not found.
    """
    if len(data) < 5 or data[:4] != _GC_HEADER or data[4] not in _GC_DATA_STRUCTS:
        return None
    gc_struct, info_len = _GC_DATA_STRUCTS[data[4]]
    if len(data) != gc_struct.size:
        return None

    vals = gc_struct.unpack(data)

    # vals indices:
    # [0]  header (bytes)       [1]  version          [2]  packetNumber
    # [3]  playersPerTeam       [4]  competitionType   [5]  stopped
    # [6]  gamePhase            [7]  state             [8]  setPlay
    # [9]  firstHalf            [10] kickingTeam       [11] secsRemaining
    # [12] secondaryTime
    # [13..] team 0: 6B + 2H + 20*info_len B, then team 1: same layout

    gc = GameControllerData(
        version=vals[1],
        packet_number=vals[2],
        players_per_team=vals[3],
        competition_type=vals[4],
        stopped=bool(vals[5]),
        game_phase=vals[6],
        state=vals[7],
        set_play=vals[8],
        first_half=bool(vals[9]),
        kicking_team=vals[10],
        secs_remaining=vals[11],
        secondary_time=vals[12],
    )

    offset = 13
    for _ in range(2):
        team = TeamInfo(
            team_number=vals[offset],
            field_player_colour=vals[offset + 1],
            goalkeeper_colour=vals[offset + 2],
            goalkeeper=vals[offset + 3],
            score=vals[offset + 4],
            penalty_shot=vals[offset + 5],
            single_shots=vals[offset + 6],
            message_budget=vals[offset + 7],
        )
        offset += 8  # consumed 6B + 2H
        for _ in range(MAX_NUM_PLAYERS):
            team.players.append(RobotInfo(
                penalty=vals[offset],
                secs_till_unpenalised=vals[offset + 1],
                warnings=vals[offset + 2] if info_len == 4 else 0,  # v20 has no warnings
                cautions=vals[offset + info_len - 1],
            ))
            offset += info_len
        gc.teams.append(team)

    if own_team is not None:
        if gc.teams[0].team_number == own_team:
            gc.own_team_index = 0
        elif gc.teams[1].team_number == own_team:
            gc.own_team_index = 1

    return gc

# ---------------------------------------------------------------------------
# Return message packing
# ---------------------------------------------------------------------------

def pack_gc_return(
    player_num: int,
    team_num: int,
    fallen: bool = False,
    pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ball_age: float = -1.0,
    ball: tuple[float, float] = (0.0, 0.0),
) -> bytes:
    """Pack a RoboCupGameControlReturnData struct into bytes ready to send.

    pose    -- (x, y, theta) in millimetres / radians, field-relative
    ball_age -- seconds since the robot last saw the ball; -1 if never seen
    ball    -- (x, y) of ball relative to robot, in millimetres
    """
    return _GC_RETURN_STRUCT.pack(
        _GC_RETURN_HEADER,
        _GC_RETURN_VER,
        player_num,
        team_num,
        int(fallen),
        pose[0], pose[1], pose[2],
        ball_age,
        ball[0], ball[1],
    )

# ---------------------------------------------------------------------------
# Background receiver
# ---------------------------------------------------------------------------

# A packet older than this means the GameController is gone (it sends at 2 Hz).
STALE_S = 2.0

class GCReceiver:
    """Bind to (host, port) and receive GameControllerData packets in a daemon thread.

    Mirrors the design of UDPReceiver in socket_client.py.

    Usage::

        receiver = GCReceiver(own_team=42)
        receiver.start()

        # inside the animation/main loop:
        gc = receiver.latest()
        if gc is not None:
            print(gc.state_name, gc.secs_remaining)

        receiver.stop()
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = GC_DATA_PORT,
        own_team: Optional[int] = None,
    ) -> None:
        self._addr = (host, port)
        self._own_team = own_team
        self._last: Optional[GameControllerData] = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="GCReceiver")
        
        self.last_packet_time = 0.0
        self.last_sender = ""  # IP of the last GameController packet (pages show it in a tooltip)
        self.is_external_gc_online = False
        self.on_packet = None  # called with (sender IP, raw bytes) for every valid packet (session recorder)

    @property
    def external_gc_online(self) -> bool:
        if time.time() - self.last_packet_time > STALE_S:
            return False
        return self.is_external_gc_online

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> Optional[GameControllerData]:
        """Return the newest packet, or None if none arrived in the last STALE_S seconds.

        It does not consume the packet: /state and the /control 403 rule run in
        different HTTP threads and must both see the current game state.
        """
        if self._last is None or time.time() - self.last_packet_time > STALE_S:
            return None
        return self._last

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(self._addr)
        print(f"[GCReceiver] Listening on {self._addr[0]}:{self._addr[1]}")

        try:
            while not self._stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                gc = parse_gc_packet(data, self._own_team)
                if gc is None:
                    print("[GCReceiver] Malformed or unexpected packet, skipping")
                    continue

                self._last = gc
                self.last_packet_time = time.time()
                self.last_sender = addr[0]
                self.is_external_gc_online = (gc.competition_type != 42)
                if self.on_packet is not None:
                    self.on_packet(addr[0], data)
        finally:
            sock.close()
            print("[GCReceiver] Socket closed.")


if __name__ == "__main__":
    # Self-check: python3 src/gc_client.py
    def _packet(version: int) -> bytes:
        gc_struct, info_len = _GC_DATA_STRUCTS[version]
        player = (5, 30, 1) if info_len == 3 else (5, 30, 2, 1)  # penalty, secs, [warnings,] cautions
        idle = (0,) * info_len
        team = lambda number, score: (number, 0, 1, 1, score, 0, 0, 1200, *player, *idle * (MAX_NUM_PLAYERS - 1))  # noqa: E731
        header = (_GC_HEADER, version, 7, 5, 1, 0, 0, STATE_PLAYING, 0, 1, 19, 300, 0)
        return gc_struct.pack(*header, *team(19, 2), *team(4, 1))

    for v in (20, 19):
        gc = parse_gc_packet(_packet(v), own_team=4)
        assert gc is not None, f"v{v} packet rejected"
        assert (gc.version, gc.state_name, gc.secs_remaining, gc.kicking_team) == (v, "PLAYING", 300, 19)
        assert [t.score for t in gc.teams] == [2, 1] and gc.own_team_index == 1
        assert [t.message_budget for t in gc.teams] == [1200, 1200]
        p = gc.teams[0].players[0]
        assert (p.penalty, p.secs_till_unpenalised, p.cautions) == (5, 30, 1)
        assert p.warnings == (2 if v == 19 else 0)
        assert gc.teams[1].players[1].penalty == 0

    assert parse_gc_packet(_packet(20)[:-1]) is None              # truncated
    assert parse_gc_packet(b"RGme\x15" + _packet(20)[5:]) is None   # unknown version 21
    assert parse_gc_packet(b"XXXX" + _packet(20)[4:]) is None       # wrong header

    # latest() must give the same packet to every caller (HTTP threads) until it is stale.
    rx = GCReceiver(host="127.0.0.1", port=0)
    rx._last, rx.last_packet_time = parse_gc_packet(_packet(20)), time.time()
    assert rx.latest() is not None and rx.latest() is not None
    rx.last_packet_time -= STALE_S + 0.1
    assert rx.latest() is None
    print("gc_client self-check OK (v19, v20, latest)")
