"""Self-check of the GET UP / SIT / GO TO rules of src/control_server.py (POST /stop getup|sit, POST /goto,
GET /positions): HTTP codes 200/400/403/409/423, the datagrams, and the frame (a blue robot gets its own frame).
In-process: no UDP receiver, no robot; it does not touch ports 8080/10006/10007.
Run: python3 tools/test_goto.py   (exit 0 = pass)"""
import json
import math
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from types import SimpleNamespace as N

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import control_server as cs  # noqa: E402

s = cs.ControlServer()
for part in (s.udp_receiver, s.gc_receiver, s.events, s.camera_hub):
    part.start = lambda: None  # HTTP only
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    s.http_port = probe.getsockname()[1]

red = N(ip="10.0.0.2", id=2, team=19, color="red", latch="", sys={"link": "control"}, robot="t1")
blue = N(ip="10.0.0.3", id=3, team=19, color="blue", latch="", sys={"link": "control"}, robot="t1")
match = N(ip="10.0.0.4", id=4, team=19, color="red", latch="", sys={"link": "telemetry"}, robot="t2")
damped = N(ip="10.0.0.5", id=5, team=19, color="red", latch="damp", sys={"link": "control"}, robot="t2")
agents = [red, blue, match, damped]
s.udp_receiver.latest = lambda: N(agents=agents)
s.udp_receiver.link_stats = lambda: {a.ip: {"age": 0.1} for a in agents}
gc = {"now": None}
s.gc_receiver.latest = lambda: gc["now"]
sent = []
s.send_joystick = lambda ips, fields, repeat=3: sent.append((list(ips), fields))
s.events.add = lambda *a, **k: None
s.start()
base = f"http://127.0.0.1:{s.http_port}"


def call(path, body=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


A = {"client": "tab-a", "name": "A"}
try:
    code, pos = call("/positions")
    assert code == 200 and pos["frame"] == "team" and pos["positions"][0]["id"] == "ready_1", pos
    r1 = next(p for p in pos["positions"] if p["id"] == "ready_1")
    assert (r1["x"], r1["y"], r1["player"]) == (-10.5, 0.0, 1)
    assert all(p["x"] < 0 for p in pos["positions"]), "our own half"
    code, bp = call("/positions?robot=10.0.0.3")
    assert code == 200 and bp["frame"] == "field" and bp["positions"][0]["x"] == 10.5, "blue: mirrored"
    assert call("/positions?robot=10.0.0.2")[1]["positions"][0]["x"] == -10.5, "red: as is"
    assert call("/positions?robot=10.9.9.9")[0] == 409

    # GET UP / SIT through /stop
    assert call("/stop", {"robot": red.ip, "kind": "getup", **A}) == (200, {"status": "sent", "kind": "getup", "targets": [red.ip], "names": ["T19 R2 (10.0.0.2)"]})
    assert sent[-1] == ([red.ip], {"isManual": True, "getup": True})
    assert call("/stop", {"robot": red.ip, "kind": "sit", **A})[0] == 409, "sit: T2 only"
    red.robot = "t2"
    assert call("/stop", {"robot": red.ip, "kind": "sit", **A})[0] == 200 and sent[-1][1] == {"isManual": True, "sit": True}
    assert call("/stop", {"robot": "all", "kind": "sit", **A})[0] == 200 and sent[-1][0] == [red.ip], "all: T2 only"
    assert call("/stop", {"robot": red.ip, "kind": "getup", "client": "tab-b", "name": "B"})[0] == 423, "lock held by A"
    assert call("/stop", {"robot": match.ip, "kind": "getup", **A})[0] == 409, "match mode"
    assert call("/stop", {"robot": damped.ip, "kind": "getup", **A})[0] == 409, "damped"
    gc["now"] = N(state=3, state_name="PLAYING")
    n = len(sent)
    assert call("/stop", {"robot": red.ip, "kind": "getup", **A})[0] == 403 and len(sent) == n, "PLAYING, no override"
    assert call("/stop", {"robot": red.ip, "kind": "getup", "testingOverride": True, **A})[0] == 200
    assert call("/stop", {"robot": red.ip, "kind": "stop", **A})[0] == 200, "STOP passes the GameController rule"

    # GO TO
    assert call("/goto", {"robot": red.ip, "x": 1, "y": 2, "theta": 0.5, **A})[0] == 403, "PLAYING, no override"
    gc["now"] = N(state=0, state_name="INITIAL")
    code, body = call("/goto", {"robot": red.ip, "x": 1, "y": 2, "theta": 0.5, **A})
    assert code == 200 and body == {"status": "sent", "target": {"x": 1.0, "y": 2.0, "theta": 0.5}}, body
    assert sent[-1] == ([red.ip], {"isManual": True, "goto": {"x": 1.0, "y": 2.0, "theta": 0.5}})
    code, body = call("/goto", {"robot": blue.ip, "x": 1, "y": 2, "theta": 0.5, **A})
    g = sent[-1][1]["goto"]
    assert code == 200 and (g["x"], g["y"]) == (-1.0, -2.0) and math.isclose(g["theta"], 0.5 - math.pi), "blue: own frame"
    code, body = call("/goto", {"robot": blue.ip, "pos": "ready_2", **A})
    assert code == 200 and sent[-1][1]["goto"] == {"x": -7.5, "y": 1.0, "theta": 0.0}, "pos: team frame, never mirrored"
    assert body["target"]["x"] == 7.5 and body["pos"] == "ready_2", "reply in the field frame"
    assert call("/goto", {"robot": red.ip, "pos": "nowhere", **A})[0] == 400
    assert call("/goto", {"robot": red.ip, "x": 30, "y": 0, "theta": 0, **A})[0] == 400, "off the field"
    assert call("/goto", {"robot": red.ip, "x": "nan", "y": 0, "theta": 0, **A})[0] == 400
    assert call("/goto", {"robot": red.ip, "x": 1, **A})[0] == 400
    assert call("/goto", {"robot": "all", "x": 1, "y": 0, "theta": 0, **A})[0] == 409
    assert call("/goto", {"robot": "10.9.9.9", "x": 1, "y": 0, "theta": 0, **A})[0] == 409
    assert call("/goto", {"robot": match.ip, "x": 1, "y": 0, "theta": 0, **A})[0] == 409
    assert call("/goto", {"robot": damped.ip, "x": 1, "y": 0, "theta": 0, **A})[0] == 409
    assert call("/goto", {"robot": red.ip, "x": 1, "y": 0, "theta": 0, "client": "tab-b"})[0] == 423
    assert call("/goto", {"robot": red.ip, "cancel": True, **A}) == (200, {"status": "sent", "cancel": True})
    assert sent[-1] == ([red.ip], {"isManual": True, "gotoCancel": True})

    # the CLI (src/oraculum_cli.py) against this gateway: its own client id, so tab-a releases the lock first
    call("/control_lock", {"action": "release", "client": "tab-a"})
    cli = [sys.executable, str(pathlib.Path(__file__).resolve().parent.parent / "src" / "oraculum_cli.py")]
    env = {**os.environ, "ORACULUM_URL": base}

    def run(*args):
        return subprocess.run(cli + list(args), env=env, capture_output=True, text=True, timeout=20)
    red.robot = "t1"
    assert run("getup", "--ip", red.ip).returncode == 0 and sent[-1] == ([red.ip], {"isManual": True, "getup": True})
    assert run("goto", "--ip", red.ip, "--pos", "ready_2").returncode == 0 and sent[-1][1]["goto"] == {"x": -7.5, "y": 1.0, "theta": 0.0}
    assert run("goto", "--ip", blue.ip, "--x", "1", "--y", "2", "--theta", "0").returncode == 0 and sent[-1][1]["goto"]["x"] == -1.0
    assert run("goto", "--ip", red.ip, "--cancel").returncode == 0 and sent[-1][1] == {"isManual": True, "gotoCancel": True}
    out = run("goto", "--list")
    assert out.returncode == 0 and "ready_1" in out.stdout and "sideline_penalized" in out.stdout, out
    n = len(sent)
    out = run("sit", "--ip", red.ip)
    assert out.returncode != 0 and "only on the T2" in out.stdout and len(sent) == n, out

    # telemetry: a blue robot's goto target is mirrored with its pose
    import socket_client as sc
    msg = sc.GameStateMsg.from_dict({"agents": [{"id": 3, "x": 1, "y": 2, "color": "blue", "latch": "goto",
                                                 "goto": {"x": -7.5, "y": 1.0, "theta": 0.0}}]})
    sc.mirror_packet(msg)
    assert msg.agents[0].goto["x"] == 7.5 and msg.agents[0].goto["y"] == -1.0 and math.isclose(abs(msg.agents[0].goto["theta"]), math.pi)
    print("getup / sit / goto rules: ok")
finally:
    s.http_server.shutdown()
    time.sleep(0.1)
