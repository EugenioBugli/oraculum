"""Session recording and the event log of the oraculum gateway.

Recorder: while a recording runs, every telemetry packet (UDP 10006) and every GameController packet
(UDP 3838) goes to recordings/rec_<YYYYMMDD>_<HHMMSS>.jsonl, one JSON object per line:
    {"t": 12.345, "src": "192.168.1.24", "data": {...telemetry packet as the robot sent it...}}
    {"t": 12.400, "src": "192.168.1.1", "gc": "<base64 GameController packet>"}
    {"t": 13.000, "event": {...}}        an event of the log (see EventLog)
    {"t": 14.000, "event_delete": 17}    a log row deleted by a user
"t" is seconds since the start of the recording. tools/replay_rrd.py replays a recording in real time.

EventLog: compares the GameController and the robots 5 times per second and logs what changed
(game state, set play, goal, penalty, robot online/offline, fall, role, low battery), plus the
events a user adds by hand. Pages read it with GET /events?since=<id>.

    python3 src/session.py      # self-check (no network)
"""

import base64
import collections
import datetime
import json
import os
import threading
import time

# one penalty and set-play table for the pages and the events
from gc_client import PENALTY_NAMES, SET_PLAY_NAMES, STATE_NAMES

ROLE_WORDS = {"G": "Goalkeeper", "D": "Defender", "M": "Midfielder", "A": "Attacker"}  # the fake sender sends letters
LOW_BATTERY = 20.0  # percent


class Recorder:
    """Writes one recording at a time; thread-safe (the UDP, GC and HTTP threads all write)."""

    def __init__(self, folder: str, max_bytes: int = 1 << 30) -> None:
        self.folder = folder
        self.max_bytes = max_bytes  # ponytail: one size cap; /DATA is nearly full
        self._lock = threading.Lock()
        self._file = None
        self.name = None
        self.by = ""  # who started the running recording (operator name or client IP)
        self.t0 = 0.0
        self.bytes = 0
        self.on_stop = None  # called with the reason when the size cap stops the recording

    def start(self, by: str = "") -> str:
        """Start a recording; while one runs, return the running one (a second client does not restart it)."""
        with self._lock:
            if self._file is None:
                self.by = by
                os.makedirs(self.folder, exist_ok=True)
                self.name = datetime.datetime.now().strftime("rec_%Y%m%d_%H%M%S")
                self._file = open(os.path.join(self.folder, self.name + ".jsonl"), "a", encoding="utf-8")
                self.t0 = time.time()
                self.bytes = 0
            return self.name

    def stop(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def status(self) -> dict:
        with self._lock:
            return {"on": self._file is not None, "name": self.name, "secs": round(time.time() - self.t0, 1) if self._file else 0,
                    "bytes": self.bytes, "by": self.by}

    def list(self) -> list:
        """Recordings on disk, newest first: [{name, bytes, mtime}] (telemetry .jsonl, not video)."""
        try:
            files = [f for f in os.listdir(self.folder) if f.startswith("rec_") and f.endswith(".jsonl")]
        except OSError:
            return []
        out = []
        for f in files:
            st = os.stat(os.path.join(self.folder, f))
            out.append({"name": f[:-6], "bytes": st.st_size, "mtime": round(st.st_mtime)})
        return sorted(out, key=lambda r: r["name"], reverse=True)

    def offset(self) -> float:
        """Seconds since the start of the running recording; 0 when none runs."""
        return round(time.time() - self.t0, 3) if self._file is not None else 0.0

    def _write(self, obj: dict) -> None:
        stopped = False
        with self._lock:
            if self._file is None:
                return
            line = json.dumps({"t": round(time.time() - self.t0, 3), **obj}, separators=(",", ":")) + "\n"
            self._file.write(line)
            self.bytes += len(line)
            if self.bytes >= self.max_bytes:
                self._file.close()
                self._file = None
                stopped = True
        if stopped and self.on_stop:
            self.on_stop(f"size limit {self.max_bytes >> 20} MB")

    def write_telemetry(self, src: str, packet: str) -> None:
        if self._file is None:  # no recording: skip the JSON parse (every packet comes here)
            return
        try:
            data = json.loads(packet, strict=False)
        except ValueError:
            return
        self._write({"src": src, "data": data})

    def write_gc(self, src: str, packet: bytes) -> None:
        self._write({"src": src, "gc": base64.b64encode(packet).decode()})

    def write_event(self, event: dict) -> None:
        self._write({"event": event})

    def write_delete(self, event_id: int) -> None:
        self._write({"event_delete": event_id})


def robot_name(agent: dict) -> str:
    return f"T{agent.get('team') or '?'} R{agent.get('id')}"


class EventLog:
    """Detects events from the receivers' state; keeps the last 5000 in memory."""

    def __init__(self, udp_receiver, gc_receiver, recorder: Recorder) -> None:
        self._udp = udp_receiver
        self._gc = gc_receiver
        self.recorder = recorder
        self._lock = threading.Lock()
        self._events = collections.deque(maxlen=5000)
        self._next_id = 1
        self._prev_gc = None      # last GameControllerData
        self._prev_robots = {}    # robot key -> agent dict
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="EventLog")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    # -- API used by the HTTP handler ----------------------------------------------------------

    def add(self, type_: str, src: str, text: str, robot: str = "") -> dict:
        gc = self._gc.latest() if self._gc else None
        with self._lock:
            event = {"id": self._next_id, "t": round(time.time(), 3),
                     "clock": gc.secs_remaining if gc else None, "phase": gc.state_name if gc else "",
                     "type": type_, "src": src, "robot": robot, "text": text,
                     "rec": self.recorder.name if self.recorder.status()["on"] else None,
                     "rec_t": self.recorder.offset()}
            self._next_id += 1
            self._events.append(event)
        self.recorder.write_event(event)
        return event

    def delete(self, event_id: int) -> bool:
        with self._lock:
            for e in self._events:
                if e["id"] == event_id:
                    self._events.remove(e)
                    break
            else:
                return False
        self.recorder.write_delete(event_id)
        return True

    def since(self, event_id: int = 0) -> list:
        with self._lock:
            return [e for e in self._events if e["id"] > event_id]

    def ids(self) -> list:
        """Ids still in the log: a page drops rows that another user deleted."""
        with self._lock:
            return [e["id"] for e in self._events]

    # -- detection -----------------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.wait(0.2):
            try:
                self.check(self._gc.latest(), self._udp.latest())
            except Exception as exc:  # a detection bug must not stop the log
                print(f"[EventLog] {exc!r}")

    def check(self, gc, state) -> None:
        """Compare with the previous call and log the differences."""
        self._check_gc(gc)
        robots = {}
        for a in (state.agents if state else []):
            d = a if isinstance(a, dict) else a.__dict__
            robots[f"{d.get('ip')}|{d.get('id')}"] = dict(d)
        prev = self._prev_robots
        for key, a in robots.items():
            name = robot_name(a)
            p = prev.get(key)
            if p is None:
                self.add("ONLINE", "robot", f"{name} sends data ({a.get('ip')})", name)
                continue
            if a.get("fallen") and not p.get("fallen"):
                self.add("FALL", "robot", f"{name} fell", name)
            if a.get("role") != p.get("role"):
                was, now = (ROLE_WORDS.get(r, r) for r in (p.get("role"), a.get("role")))
                self.add("ROLE", "robot", f"{name}: {was} → {now}", name)
            b, pb = (v if isinstance(v, (int, float)) else -1 for v in (a.get("battery"), p.get("battery")))
            if 0 <= b < LOW_BATTERY <= pb:
                self.add("BATTERY", "robot", f"{name} battery {b:.0f} %", name)
        for key, p in prev.items():
            if key not in robots:
                self.add("OFFLINE", "robot", f"{robot_name(p)} stopped sending", robot_name(p))
        self._prev_robots = robots

    def _check_gc(self, gc) -> None:
        p = self._prev_gc
        self._prev_gc = gc
        if gc is None:
            if p is not None:
                self.add("GC", "gc", "GameController silent")
            return
        if p is None:
            self.add("GC", "gc", f"GameController online: {gc.state_name}")
            return
        if gc.state != p.state:
            self.add("PHASE", "gc", STATE_NAMES.get(gc.state, str(gc.state)))
        if gc.first_half != p.first_half:
            self.add("PHASE", "gc", "first half" if gc.first_half else "second half")
        if gc.set_play != p.set_play and gc.set_play:
            team = gc.kicking_team
            self.add("SETPLAY", "gc", f"{SET_PLAY_NAMES.get(gc.set_play, gc.set_play)} for team {team}")
        for t, pt in zip(gc.teams, p.teams):
            if t.score > pt.score:
                self.add("GOAL", "gc", f"goal team {t.team_number} ({gc.teams[0].score}-{gc.teams[1].score})")
            for n, (r, pr) in enumerate(zip(t.players, pt.players), start=1):
                if r.penalty != pr.penalty:
                    who = f"T{t.team_number} R{n}"
                    if r.penalty:
                        self.add("PENALTY", "gc", f"{who}: {PENALTY_NAMES.get(r.penalty, r.penalty)}", who)
                    else:
                        self.add("PENALTY", "gc", f"{who}: back in play", who)


if __name__ == "__main__":
    import tempfile

    from gc_client import GameControllerData, RobotInfo, TeamInfo

    class _GC:
        value = None

        def latest(self):
            return self.value

    def _gc(state, score=0, penalty=0, set_play=0):
        teams = [TeamInfo(team_number=19, score=score, players=[RobotInfo(penalty=penalty)]),
                 TeamInfo(team_number=5, players=[RobotInfo()])]
        return GameControllerData(state=state, teams=teams, set_play=set_play, kicking_team=19, secs_remaining=600)

    class _State:
        def __init__(self, agents):
            self.agents = agents

    with tempfile.TemporaryDirectory() as tmp:
        rec = Recorder(tmp)
        gcr = _GC()
        log = EventLog(None, gcr, rec)
        rec.start()
        log.check(None, None)
        assert log.since() == []
        gcr.value = _gc(0)
        log.check(gcr.value, None)
        gcr.value = _gc(3, score=1, penalty=5, set_play=6)
        robot = {"ip": "10.0.0.2", "id": 3, "team": 19, "role": "Striker", "fallen": False, "battery": 50}
        log.check(gcr.value, _State([robot]))
        log.check(gcr.value, _State([dict(robot, fallen=True, battery=10, role="Defender")]))
        log.check(gcr.value, _State([]))
        types = [e["type"] for e in log.since()]
        assert types == ["GC", "PHASE", "SETPLAY", "GOAL", "PENALTY", "ONLINE", "FALL", "ROLE", "BATTERY", "OFFLINE"], types
        assert log.since()[1]["text"] == "PLAYING" and log.since()[1]["clock"] == 600
        e = log.add("MARK", "manual", "bad kick", "T19 R3")
        assert log.delete(e["id"]) and not log.delete(e["id"]) and e["id"] not in log.ids()
        rec.write_telemetry("10.0.0.2", '{"agents": []}')
        rec.write_gc("10.0.0.1", b"RGme")
        name = rec.name
        rec.stop()
        rows = [json.loads(line) for line in open(os.path.join(tmp, name + ".jsonl"))]
        assert all(isinstance(r["t"], float) for r in rows), rows[:2]
        assert sum("event" in r for r in rows) == 11 and rows[-3]["event_delete"] == e["id"]
        assert rows[-2] == {"t": rows[-2]["t"], "src": "10.0.0.2", "data": {"agents": []}}
        assert base64.b64decode(rows[-1]["gc"]) == b"RGme"
        small = Recorder(tmp, max_bytes=10)
        reasons = []
        small.on_stop = reasons.append
        small.start()
        small.write_gc("x", b"0123456789")
        assert not small.status()["on"] and reasons == ["size limit 0 MB"]
    print("session self-check OK")
