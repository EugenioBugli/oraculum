"""Self-check of the match switch of src/control_server.py (config.yaml `match`, env ORACULUM_MATCH): in match mode the
gateway sends NO datagram (joystick, /stop, /goto, camera requests, simulated referee), the command routes answer 409,
/state carries "match": true, ORACULUM_SIM_GC / ORACULUM_CONTROL_IP are ignored. With the switch off, camera requests
still skip match robots (sys.link "telemetry"). HSL rules @06c44d4b, rules/robot_players.tex L285-289.
In-process: every UDP send is caught at the socket class (nothing leaves); it does not touch ports 8080/10006/10007.
Run: python3 tools/test_match.py   (exit 0 = pass)"""
import json
import os
import pathlib
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
from types import SimpleNamespace as N

udp = []  # (data, address) of every datagram any code in this process tried to send


class Rec(socket.socket):  # ponytail: catch at the socket class, so a send path nobody knows about is caught as well
    def sendto(self, data, *args):
        udp.append((data, args[-1]))
        return len(data)

    def send(self, data, *args):
        if self.type == socket.SOCK_DGRAM:  # TCP (the HTTP server and urllib) sends for real
            udp.append((data, None))
            return len(data)
        return super().send(data, *args)


socket.socket = Rec
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import control_server as cs  # noqa: E402

for k in ("ORACULUM_MATCH", "ORACULUM_SIM_GC", "ORACULUM_CONTROL_IP", "ORACULUM_GC_TARGETS"):
    os.environ.pop(k, None)

# config.yaml `match` and the env override
with tempfile.TemporaryDirectory() as tmp:
    cfg = pathlib.Path(tmp) / "config.yaml"
    cfg.write_text((ROOT / "config.yaml").read_text().replace("\nmatch: false", "\nmatch: true"))
    for env, want in ((None, True), ("0", False), ("1", True)):
        if env is not None:
            os.environ["ORACULUM_MATCH"] = env
        x = cs.ControlServer(str(cfg))
        x.camera_hub._sock.close()
        assert x.match is want, (env, x.match)
    os.environ.pop("ORACULUM_MATCH")

os.environ.update(ORACULUM_MATCH="1", ORACULUM_SIM_GC="19,20", ORACULUM_CONTROL_IP="10.9.9.9")
s = cs.ControlServer()
assert s.match and s.sim_gc is None, "no simulated referee in match mode"
assert s.gc_receiver._addr[1] == s.config["game_controller"]["port"], "the GameController port, listen-only"
assert s.control_ip == ""
for part in (s.udp_receiver, s.gc_receiver, s.events, s.reception):
    part.start = lambda: None
s.camera_hub.start = lambda: None
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    s.http_port = probe.getsockname()[1]

ctl = N(ip="10.0.0.2", id=2, team=19, color="red", latch="", sys={"link": "control"}, robot="t2")
tel = N(ip="10.0.0.4", id=4, team=19, color="red", latch="", sys={"link": "telemetry"}, robot="t2")
agents = [ctl, tel]
s.udp_receiver.latest = lambda: N(agents=agents, to_dict=lambda: {"agents": [], "ball": None, "drawings": [], "texts": []})
s.udp_receiver.link_stats = lambda: {a.ip: {"age": 0.1} for a in agents}
s.gc_receiver.latest = lambda: None
s.events.add = lambda *a, **k: None
s.git_head = lambda: ""
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
    code, st = call("/state?client=tab-a")
    assert code == 200 and st["match"] is True, st
    assert call("/control_lock", {"action": "take", **A})[0] == 200, "the lock still works (it sends nothing)"
    code, body = call("/control", {"ip": ctl.ip, "isManual": True, "vx": 0.3, **A})
    assert code == 409 and "Match mode" in body["error"] and "L285" in body["error"], body
    assert call("/control", {"disabled_drawings": "a,b"})[0] == 200, "a filter-only body sends nothing: still 200"
    for kind in ("stop", "lie", "resume", "getup", "sit"):
        for robot in (ctl.ip, "all"):
            assert call("/stop", {"robot": robot, "kind": kind, **A})[0] == 409, (kind, robot)
    assert call("/stop", {"robot": ctl.ip, "kind": "damp", "confirm": ctl.ip, **A})[0] == 409
    assert call("/stop", {"robot": ctl.ip, "kind": "nonsense", **A})[0] == 409, "409 before any other rule"
    assert call("/goto", {"robot": ctl.ip, "pos": "ready_2", **A})[0] == 409
    assert call("/goto", {"robot": ctl.ip, "cancel": True, **A})[0] == 409
    assert call("/gc", {"state": "playing"})[0] == 409
    assert call(f"/camera?robot={ctl.ip}|2")[0] == 200, "a frame (if any) is still served"
    s.send_joystick([ctl.ip], {"isManual": True, "stop": True})  # the guard inside, not only the routes
    s.camera_hub.request(tel.ip, 4)
    assert call("/events", {"add": {"text": "mark"}})[0] == 200, "marks and recording stay"
    time.sleep(0.5)  # send_joystick sends from a thread
    assert udp == [], f"match mode sent {udp}"

    # Switch off: the same routes send (the socket catch works), and camera requests skip match robots
    s.match = False
    assert call("/stop", {"robot": ctl.ip, "kind": "stop", **A})[0] == 200
    time.sleep(0.5)
    assert udp and all(t == (ctl.ip, 10007) for _, t in udp), udp
    udp.clear()
    assert call(f"/camera?robot={tel.ip}|4")[0] == 200 and udp == [], "no camera request to a match robot"
    assert call(f"/camera?robot={ctl.ip}|2")[0] == 200 and [t for _, t in udp] == [(ctl.ip, 10008)], udp
    assert call("/state")[1]["match"] is False
    print("match switch: ok")
finally:
    s.http_server.shutdown()
    time.sleep(0.1)
