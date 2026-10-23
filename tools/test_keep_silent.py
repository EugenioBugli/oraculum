"""Self-check of the keep rule in src/socket_client.py UDPReceiver.latest(): a silent sender's robots stay in /state
for KEEP_SILENT_S (the pages grey them), without their drawings and without a say in the team ball.
Run: python3 tools/test_keep_silent.py   (exit 0 = pass)"""
import pathlib
import sys
import time
from types import SimpleNamespace as N

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import socket_client as sc  # noqa: E402

sc.GameStateMsg = lambda **k: N(**k)  # only the fields latest() fills
r = sc.UDPReceiver("127.0.0.1", 0)  # not started: no socket
t0 = 1000.0
r._cached_agents = {("10.0.0.1", 3): N(id=3, x=0, y=0, ball={"x": 1.0, "y": 0.0}),
                    ("10.0.0.2", 4): N(id=4, x=5, y=0, ball={"x": 4.0, "y": 0.0})}
r._cached_drawings = {("10.0.0.1", 3, "/p"): N(path="/p")}
r._agent_times = {("10.0.0.1", 3): t0, ("10.0.0.2", 4): t0 + 5}
r._last_update_times = {"10.0.0.1": t0, "10.0.0.2": t0 + 5}


def at(t):
    real, time.time = time.time, lambda: t
    try:
        return r.latest()
    finally:
        time.time = real


m = at(t0 + 5)
assert sorted(a.id for a in m.agents) == [3, 4], "a robot of a silent sender stays"
assert m.drawings == [], "no drawings of a silent sender"
assert m.ball.x == 4.0, "the team ball comes only from robots that still send"
assert [a.id for a in at(t0 + sc.KEEP_SILENT_S + 0.5).agents] == [4], "dropped after KEEP_SILENT_S"
print("keep rule: ok")
