"""GameController UDP receiver and return-message sender.

The GameController broadcasts RoboCupGameControlData (198 bytes) on UDP port 3838.
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

import dataclasses
import queue
import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Constants  (mirror RoboCupGameControlData.h)
# ---------------------------------------------------------------------------

GC_DATA_PORT   = 3838
GC_RETURN_PORT = 3939

_GC_HEADER        = b"RGme"
_GC_VERSION       = 19
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

# ---------------------------------------------------------------------------
# Binary struct formats  (little-endian, matching x86 GameController output)
#
# RoboCupGameControlData layout (198 bytes):
#   header[4]           4s
#   version..kickingTeam  10B  (10 uint8 fields)
#   secsRemaining         h    (int16)
#   secondaryTime         h    (int16)
#   teams[2]:  each TeamInfo = 6B + 2H + 20*(4B)  = 90 bytes
#
# RoboCupGameControlReturnData layout (32 bytes):
#   header[4]  4s
#   version+playerNum+teamNum+fallen  4B
#   pose[3]+ballAge+ball[2]           6f
# ---------------------------------------------------------------------------

_GC_DATA_FMT = "<4s10Bhh" + ("6B2H" + "4B" * MAX_NUM_PLAYERS) * 2
_GC_DATA_STRUCT = struct.Struct(_GC_DATA_FMT)
assert _GC_DATA_STRUCT.size == 198, f"Unexpected GC struct size: {_GC_DATA_STRUCT.size}"

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
    if len(data) != _GC_DATA_STRUCT.size:
        return None

    vals = _GC_DATA_STRUCT.unpack(data)

    # vals indices:
    # [0]  header (bytes)       [1]  version          [2]  packetNumber
    # [3]  playersPerTeam       [4]  competitionType   [5]  stopped
    # [6]  gamePhase            [7]  state             [8]  setPlay
    # [9]  firstHalf            [10] kickingTeam       [11] secsRemaining
    # [12] secondaryTime
    # [13..100] team 0: 6B + 2H + 80B  (88 elements)
    # [101..188] team 1: same layout

    if vals[0] != _GC_HEADER:
        return None
    if vals[1] != _GC_VERSION:
        return None

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
                warnings=vals[offset + 2],
                cautions=vals[offset + 3],
            ))
            offset += 4  # consumed 4B per RobotInfo
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
        queue_size: int = 10,
    ) -> None:
        self._addr = (host, port)
        self._own_team = own_team
        self._queue: queue.Queue[GameControllerData] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="GCReceiver")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=2.0)

    def latest(self) -> Optional[GameControllerData]:
        """Drain the queue and return the most recent packet, or None."""
        msg = None
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
        return msg

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(self._addr)
        print(f"[GCReceiver] Listening on {self._addr[0]}:{self._addr[1]}")

        try:
            while not self._stop_event.is_set():
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                gc = parse_gc_packet(data, self._own_team)
                if gc is None:
                    print("[GCReceiver] Malformed or unexpected packet, skipping")
                    continue

                if self._queue.full():
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                self._queue.put_nowait(gc)
        finally:
            sock.close()
            print("[GCReceiver] Socket closed.")
