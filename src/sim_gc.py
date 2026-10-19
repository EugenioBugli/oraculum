"""Simulated GameController for hosted sessions (oraculum/hosted).

circus sends no GameController packets, and in one container the robot and the gateway cannot share UDP 3838.
This sender keeps the game state, unicasts GameController v20 packets to the robots (default 127.0.0.1:3838) twice
per second, and hands the same state to the gateway's GCReceiver directly. POST /gc changes it. Enable it with the
environment variable ORACULUM_SIM_GC="<team A>,<team B>" (team numbers, e.g. "8,70").

    python3 src/sim_gc.py    # self-check (no network)
"""

import socket
import threading
import time

from gc_client import (
    _GC_DATA_STRUCTS,
    _GC_HEADER,
    MAX_NUM_PLAYERS,
    PENALTY_NAMES,
    STATE_FINISHED,
    STATE_INITIAL,
    STATE_NAMES,
    STATE_PLAYING,
    parse_gc_packet,
)

STATES = {name.lower(): code for code, name in STATE_NAMES.items()}  # initial, ready, set, playing, finished
HALF_SECS = 600
RED, BLUE = 1, 0  # GameController team colours


class SimGameController:
    def __init__(self, gc_receiver, teams=(8, 70), targets=(("127.0.0.1", 3838),), players=5):
        self.gc_receiver = gc_receiver
        self.teams = [int(t) for t in teams]
        self.targets = list(targets)
        self.players = players
        self._lock = threading.Lock()
        self.state, self.first_half, self.set_play = STATE_INITIAL, True, 0
        self.kicking_team, self.secs = self.teams[0], float(HALF_SECS)
        self.scores = [0, 0]
        self.penalties = {}  # (team index, player number) -> [penalty code, seconds left]
        self.packet_number = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SimGameController")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def set(self, state=None, kicking_team=None, goal=None, half=None, penalty=None) -> dict:
        """Referee action; every argument is optional. goal = team index 0/1; penalty = {team: <number>, player: 1-5,
        code: gc_client.PENALTY_NAMES key (0 = unpenalise)}, 30 s. Returns status()."""
        with self._lock:
            if state is not None:
                if str(state).lower() not in STATES:
                    raise ValueError(f"state must be one of {sorted(STATES)}")
                self.state = STATES[str(state).lower()]
                self.set_play = 0
                if self.state != STATE_FINISHED and self.secs <= 0:  # the half is over: a new half starts
                    self.first_half, self.secs = not self.first_half, float(HALF_SECS)
            if kicking_team is not None:
                if int(kicking_team) not in self.teams:
                    raise ValueError(f"kicking_team must be one of {self.teams}")
                self.kicking_team = int(kicking_team)
            if goal is not None:
                i = int(goal)
                if i not in (0, 1):
                    raise ValueError("goal must be the team index 0 or 1")
                self.scores[i] += 1
                self.kicking_team = self.teams[1 - i]  # the other team kicks off
                if self.state == STATE_PLAYING:
                    self.state = STATES["ready"]
            if half is not None:
                self.first_half = str(half) != "second"
                self.secs = float(HALF_SECS)
            if penalty is not None:
                team, player, code = int(penalty["team"]), int(penalty["player"]), int(penalty.get("code", 6))
                if team not in self.teams or not 1 <= player <= self.players or code not in PENALTY_NAMES:
                    raise ValueError(f"penalty needs team in {self.teams}, player 1-{self.players}, code in {sorted(PENALTY_NAMES)}")
                key = (self.teams.index(team), player)
                if code:
                    self.penalties[key] = [code, 30.0]
                else:
                    self.penalties.pop(key, None)
        self._publish()
        return self.status()

    def status(self) -> dict:
        with self._lock:
            return {"state": STATE_NAMES[self.state], "teams": self.teams, "scores": list(self.scores),
                    "kicking_team": self.kicking_team, "secs_remaining": int(self.secs), "first_half": self.first_half}

    def packet(self) -> bytes:
        gc_struct, info_len = _GC_DATA_STRUCTS[20]
        with self._lock:
            self.packet_number = (self.packet_number + 1) % 256
            header = (_GC_HEADER, 20, self.packet_number, self.players, 0, 0, 0, self.state, self.set_play,
                      int(self.first_half), self.kicking_team, int(self.secs), 0)
            body = []
            for i, (number, colour) in enumerate(zip(self.teams, (RED, BLUE))):
                body += [number, colour, colour, 1, self.scores[i], 0, 0, 1200]
                for player in range(1, MAX_NUM_PLAYERS + 1):  # RobotInfo: penalty, secsTillUnpenalised, cautions(, ...)
                    code, secs = self.penalties.get((i, player), (0, 0))
                    body += [code, int(secs)] + [0] * (info_len - 2)
        return gc_struct.pack(*header, *body)

    def _publish(self) -> None:
        data = self.packet()
        for target in self.targets:
            try:
                self._sock.sendto(data, target)
            except OSError as exc:  # a missing robot must not stop the referee
                print(f"[SimGameController] {target}: {exc}")
        rx = self.gc_receiver
        if rx is not None:  # the gateway sees the same packet without binding 3838
            rx._last = parse_gc_packet(data, rx._own_team)
            rx.last_packet_time = time.time()
            rx.is_external_gc_online = True

    def _run(self) -> None:
        last = time.monotonic()
        while not self._stop.wait(0.5):
            now = time.monotonic()
            with self._lock:
                for key, pen in list(self.penalties.items()):  # penalties count down in every state; 0 s ends them
                    pen[1] -= now - last
                    if pen[1] <= 0:
                        del self.penalties[key]
                if self.state == STATE_PLAYING:
                    self.secs = max(0.0, self.secs - (now - last))
                    if self.secs == 0:
                        self.state = STATE_FINISHED
            last = now
            self._publish()


if __name__ == "__main__":
    class _Rx:
        _own_team = 8
        _last = None

    rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx_sock.bind(("127.0.0.1", 0))
    rx_sock.settimeout(1.0)
    rx = _Rx()
    gc = SimGameController(rx, teams=(8, 70), targets=[rx_sock.getsockname()])
    gc.set(state="playing")
    gc_pkt = parse_gc_packet(rx_sock.recv(512), own_team=8)
    assert gc_pkt and gc_pkt.state_name == "PLAYING" and gc_pkt.own_team_index == 0 and gc_pkt.kicking_team == 8
    assert rx._last.state_name == "PLAYING" and rx.is_external_gc_online
    s = gc.set(goal=1)  # team 70 scores: state back to READY, team 8 kicks off
    assert s["scores"] == [0, 1] and s["state"] == "READY" and s["kicking_team"] == 8, s
    assert [t.score for t in parse_gc_packet(rx_sock.recv(512)).teams] == [0, 1]
    for bad in ({"state": "halftime"}, {"kicking_team": 5}, {"goal": 2}):
        try:
            gc.set(**bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass
    s = gc.set(penalty={"team": 70, "player": 3, "code": 8})
    pk = parse_gc_packet(rx_sock.recv(512), own_team=8)
    assert pk.teams[1].players[2].penalty == 8 and pk.teams[1].players[2].secs_till_unpenalised == 30, pk.teams[1].players[2]
    gc.set(penalty={"team": 70, "player": 3, "code": 0})
    assert parse_gc_packet(rx_sock.recv(512), own_team=8).teams[1].players[2].penalty == 0
    gc.set(state="playing")
    gc.secs = 0.6
    gc.start()
    time.sleep(1.3)
    gc.stop()
    assert gc.status()["state"] == "FINISHED" and gc.status()["secs_remaining"] == 0
    print("sim_gc self-check OK")
