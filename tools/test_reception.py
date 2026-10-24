"""Self-check of src/reception.py and its use in src/control_server.py: robots on ANY branch, receive-only.
- SPQRMessage in both formats ("rcap" = mappazzone / RCAP2026-DEV, "main"), detected per packet; garbage and other
  teams' formats are counted, not decoded; a branch that adds a field at the end of a nested object still decodes.
- Golden files tools/golden/*.bin (robot bytes captured on the wire, if present) decode.
- GC return packets (UDP 3939): mm -> m, robot-relative ball -> field.
- Merge per (ip, team, player): debug > team > gc while fresh, a stale source yields; sources, source_age, readonly.
- Frames: a robot of frames.mirror_team_color (colour from the GameController) is mirrored; unknown colour: not.
- Read-only robots are never command targets (/stop all, /stop <ip>, /goto, /camera); match mode sends nothing.
- Live sockets on free ports (no fixed port is touched): one team datagram and one GC return reach /state.
Every UDP send in this process is caught at the socket class; only this test's own sender socket sends for real.
Run: python3 tools/test_reception.py   (exit 0 = pass)"""
import json
import math
import os
import pathlib
import socket
import sys
import time
import urllib.error
import urllib.request

udp = []  # (data, address) of every datagram the gateway code tried to send
REAL = socket.socket


class Rec(REAL):  # catch at the socket class: a send path nobody knows about is caught as well
    def sendto(self, data, *args):
        udp.append((data, args[-1]))
        return len(data)


socket.socket = Rec
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import control_server as cs  # noqa: E402
from gc_client import pack_gc_return  # noqa: E402
from reception import Reception, decode_team_message, encode_team_message  # noqa: E402

near = lambda a, b, tol=1e-4: abs(a - b) < tol  # noqa: E731

# --- 1. SPQRMessage, both formats ------------------------------------------------------------------------------------
for fmt, size in (("rcap", 186), ("main", 154)):
    assert len(encode_team_message(fmt, 3, 1.0, -2.0, 0.5)) == size, fmt  # no NTP responses, no obstacles
    raw = encode_team_message(fmt, 4, 1.0, -2.0, math.pi / 2, role=2, status=2 if fmt == "rcap" else 0,
                              ball_local=(1.0, 0.0), obstacles=[(2.0, 0.0, 7 if fmt == "rcap" else 2)], ntp_responses=2)
    m = decode_team_message(raw)
    assert m and m["format"] == fmt and m["player"] == 4 and (m["x"], m["y"], m["theta"]) == (1.0, -2.0, m["theta"]), m
    assert near(m["theta"], math.pi / 2) and m["ball_local"] == (1.0, 0.0) and m["ntp"]
    assert m["role"] == ("LeftGuard" if fmt == "rcap" else "Striker") and m["status"] == ("penalized" if fmt == "rcap" else "")
    assert m["obstacles"] == [{"x": 2.0, "y": 0.0, "type": 2}], m["obstacles"]
    assert decode_team_message(raw[:-1]) is None and decode_team_message(raw + b"\0") is None, "exact length only"
    padded = decode_team_message(encode_team_message(fmt, 4, 1.0, -2.0, 0.0, ball_local=(0.5, 0.5), ball_pad=8))
    assert padded and padded["format"] == fmt and padded["ball_local"] == (0.5, 0.5), "a longer LocalBall still decodes"
assert decode_team_message(encode_team_message("rcap", 3, 0, 0, 0, ball_local=None))["ball_local"] is None, "not seen"
assert decode_team_message(encode_team_message("rcap", 21, 0, 0, 0)) is None, "player 1..20"
for junk in (b"", b"\x00" * 186, bytes(range(256)) * 2, b'{"agents": []}', os.urandom(300)):
    assert decode_team_message(junk) is None, junk[:20]

# Robot bytes: captured on the Jetson simulation 2026-10-23 (1v1, teams 1 and 2, robot code spqr-merge
# feature/oraculum-tcm-mappazzone @ bc462d43 = the rcap format; clip RECEPTION_20261023_205223 in
# /DATA/RoboCup/oraculum_media_2v2/jetson_clips/). No robot bytes of main's format exist here: main is synthetic only.
golden = sorted((ROOT / "tools" / "golden").glob("team_*.bin"))  # one datagram per file: team_<team>_<sender>_<n>.bin
assert len(golden) >= 4, "tools/golden/ team packets missing"
for f in golden:
    m = decode_team_message(f.read_bytes())
    assert m is not None and m["format"] == "rcap" and m["player"] == 2 and m["role"] == "Striker", f.name
    assert m["status"] == "playing" and len(m["obstacles"]) <= 4, f.name
    print(f"golden {f.name}: {m['format']} player {m['player']} pose ({m['x']:.2f}, {m['y']:.2f}, {m['theta']:.2f}) "
          f"role {m['role']} ball {m['ball_local']}")
for f in sorted((ROOT / "tools" / "golden").glob("gcret_*.bin")):
    from gc_client import parse_gc_return  # noqa: E402
    assert parse_gc_return(f.read_bytes()) is not None, f.name
    print(f"golden {f.name}: {parse_gc_return(f.read_bytes())}")

# --- 2. counting, GC return, merge, frames ---------------------------------------------------------------------------
r = Reception(own_team=19, mirror_color="blue", skip_ports={10006})
T = 1000.0
assert r.handle_team(19, "10.0.0.7", encode_team_message("main", 7, 2.0, 1.0, 0.0, ball_local=(1.0, 0.0)), now=T)
assert not r.handle_team(5, "10.0.5.1", os.urandom(120), now=T), "another team's format: counted only"
assert r.handle_gc_return("10.0.0.8", pack_gc_return(8, 5, True, (1000.0, 500.0, 0.0), 0.5, (0.0, 1000.0)), now=T)
assert not r.handle_gc_return("10.0.0.8", b"RGrt" + bytes(28), now=T), "a bad GC return is counted as invalid"
st = r.status()
assert st["teams"]["19"]["decoded"] == 1 and st["teams"]["19"]["formats"] == {"main": 1}, st
assert st["teams"]["5"]["unknown"] == 1 and st["teams"]["5"]["decoded"] == 0 and st["gc_return"]["invalid"] == 1, st

debug = {"id": 3, "team": 19, "ip": "10.0.0.3", "x": -1.0, "y": -1.0, "angle": 0.0, "role": "Striker", "color": "red",
         "ball": None, "obstacles": [], "fallen": False, "sys": {"link": "control"}}
assert r.handle_gc_return("10.0.0.3", pack_gc_return(3, 19, True, (4000.0, 0.0, 0.0)), now=T + 1)  # newer than debug
agents = r.merge([dict(debug)], {"10.0.0.3": {"age": 0.2}}, {19: "red", 5: "blue"}, now=T + 1)
by = {(a["ip"], a["id"]): a for a in agents}
d = by[("10.0.0.3", 3)]
assert (d["x"], d["fallen"], d["sources"], d["readonly"]) == (-1.0, False, ["debug", "gc"], False), "fresh debug wins"
assert d["source_age"] == {"debug": 0.2, "gc": 0.0} and d["sys"]["link"] == "control"
d = r.merge([dict(debug)], {"10.0.0.3": {"age": 5.0}}, {19: "red"}, now=T + 1)[0]
assert (d["x"], d["fallen"]) == (4.0, True), "a stale debug source yields to a fresh GC return"

tm = by[("10.0.0.7", 7)]  # team message only, team 19 = red: own frame = field frame
assert tm["readonly"] and tm["sys"]["link"] == "none" and tm["sources"] == ["team"] and tm["team_format"] == "main"
assert (tm["x"], tm["y"], tm["role"], tm["color"]) == (2.0, 1.0, "Defender", "red") and tm["ball"] == {"x": 3.0, "y": 1.0}
gc = by[("10.0.0.8", 8)]  # GC return only, team 5 = blue: mirrored, ball robot-relative (0, 1 m) -> field
assert gc["readonly"] and gc["sources"] == ["gc"] and gc["color"] == "blue" and gc["fallen"]
assert (gc["x"], gc["y"]) == (-1.0, -0.5) and near(gc["angle"], -math.pi) and gc["ball"] == {"x": -1.0, "y": -1.5}, gc
nocol = r.merge([], {}, {}, now=T + 1)  # no GameController and no debug robot of team 5: colour unknown, not mirrored
g = next(a for a in nocol if a["id"] == 8)
assert g["color"] == "" and g["frame"] == "team" and (g["x"], g["y"]) == (1.0, 0.5)

assert r.handle_team(19, "10.0.0.8", encode_team_message("rcap", 9, 0.0, 0.0, 0.0, role=1), now=T)  # same IP, other player
assert r.handle_team(5, "10.0.0.8", encode_team_message("rcap", 8, 3.0, 3.0, 0.0, role=0, status=2), now=T + 0.5)
both = next(a for a in r.merge([], {}, {5: "blue"}, now=T + 1) if a["id"] == 8 and a["team"] == 5)
assert both["sources"] == ["team", "gc"] and (both["x"], both["y"]) == (-3.0, -3.0) and both["role"] == "Goalie"
assert both["state"] == "P" and not both["fallen"], "every field of the fresh team message wins over the GC return, fallen too"
assert len(r.merge([], {}, {}, now=T + 20)) == 0, "records older than KEEP_SILENT_S are dropped"

assert Reception(own_team=6, teams=[19], teams_fn=lambda: [5, 0]).wanted_teams() == {5, 6, 19}
rr = Reception(own_team=6, skip_ports={10006}, gc_return=False)
rr._open_team_ports()
assert rr.teams[6]["error"] and not rr.teams[6]["listening"], "team 6 = port 10006 (telemetry): not shared"


# --- 3. live sockets on free ports, through the gateway: /state, command targets, match ------------------------------
def free_port():
    with REAL(socket.AF_INET, socket.SOCK_DGRAM) as p:
        p.bind(("127.0.0.1", 0))
        return p.getsockname()[1]


for k in ("ORACULUM_MATCH", "ORACULUM_SIM_GC", "ORACULUM_CONTROL_IP", "ORACULUM_GC_TARGETS"):
    os.environ.pop(k, None)
s = cs.ControlServer()
team_port, gc_port = free_port(), free_port()
s.reception = Reception(own_team=19, mirror_color="blue", host="127.0.0.1", port_base=team_port - 19,
                        gc_return_port=gc_port, teams_fn=lambda: [19, 5])
for part in (s.udp_receiver, s.gc_receiver, s.events, s.camera_hub):
    part.start = lambda: None
with REAL() as probe:
    probe.bind(("127.0.0.1", 0))
    s.http_port = probe.getsockname()[1]
dbg = {"id": 2, "team": 19, "ip": "10.0.0.2", "x": 0.0, "y": 0.0, "angle": 0.0, "color": "red", "latch": "",
       "sys": {"link": "control"}, "robot": "t2", "ball": None, "obstacles": []}
dbg_obj = type("A", (), {**dbg, "sys": {"link": "control"}})
s.udp_receiver.latest = lambda: type("S", (), {"agents": [dbg_obj], "to_dict": lambda self=None: {
    "agents": [dict(dbg)], "ball": None, "drawings": [], "texts": []}})()
s.udp_receiver.link_stats = lambda: {"10.0.0.2": {"hz": 1, "kbps": 1, "age": 0.1}}
s.gc_receiver.latest = lambda: None
s.events.add = lambda *a, **k: None
s.git_head = lambda: ""
s.start()
base = f"http://127.0.0.1:{s.http_port}"


def call(path, body=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


try:
    with REAL(socket.AF_INET, socket.SOCK_DGRAM) as tx:  # the robots: this test's own sender, the only real send
        tx.sendto(encode_team_message("rcap", 4, 1.0, 2.0, 0.0, ball_local=(1.0, 0.0)), ("127.0.0.1", team_port))
        tx.sendto(pack_gc_return(5, 5, False, (2000.0, 0.0, 0.0)), ("127.0.0.1", gc_port))
    for _ in range(40):
        st = call("/state")[1]
        if len(st["agents"]) == 3:
            break
        time.sleep(0.05)
    by = {a["id"]: a for a in st["agents"]}
    assert set(by) == {2, 4, 5}, st["agents"]
    assert by[2]["sources"] == ["debug"] and not by[2]["readonly"]
    assert by[4]["readonly"] and by[4]["sources"] == ["team"] and by[4]["team_format"] == "rcap" and by[4]["x"] == 1.0
    assert by[5]["readonly"] and by[5]["sources"] == ["gc"] and by[5]["x"] == 2.0 and by[5]["color"] == ""
    assert st["reception"]["teams"]["19"]["listening"] and st["reception"]["gc_return"]["listening"], st["reception"]
    assert st["reception"]["teams"]["19"]["decoded"] == 1 and "5" in st["reception"]["teams"], "GameController teams too"
    assert st["fleet"]["link"]["127.0.0.1"]["age"] < 2 and st["ball"] == {"x": 2.0, "y": 2.0}, st["fleet"]
    assert udp == [], f"reception sent {udp}"

    A = {"client": "tab-a", "name": "A"}
    assert call("/stop", {"robot": "all", "kind": "stop", **A})[0] == 200
    time.sleep(0.5)
    assert udp and {t for _, t in udp} == {("10.0.0.2", 10007)}, f"STOP ALL reached only the debug robot: {udp}"
    udp.clear()
    assert call("/stop", {"robot": "127.0.0.1", "kind": "stop", **A})[0] == 409, "a read-only robot takes no command"
    assert call("/goto", {"robot": "127.0.0.1", "pos": "ready_2", **A})[0] in (400, 409)
    assert call("/control", {"ip": "127.0.0.1", "isManual": True, "vx": 0.3, **A})[0] == 409, "no MANUAL to a read-only IP"
    assert call("/camera?robot=127.0.0.1|4")[0] == 200
    time.sleep(0.3)
    assert udp == [], f"a read-only robot got {udp}"

    s.match = True  # match switch: nothing at all, reception keeps working
    with REAL(socket.AF_INET, socket.SOCK_DGRAM) as tx:
        tx.sendto(encode_team_message("main", 6, 0.0, 0.0, 0.0), ("127.0.0.1", team_port))
    time.sleep(0.3)
    assert call("/stop", {"robot": "all", "kind": "stop", **A})[0] == 409
    assert {a["id"] for a in call("/state")[1]["agents"]} == {2, 4, 5, 6}
    time.sleep(0.3)
    assert udp == [], f"match mode sent {udp}"
    print(f"reception: ok ({len(golden)} golden team packets)")
finally:
    s.http_server.shutdown()
    s.reception.stop()
