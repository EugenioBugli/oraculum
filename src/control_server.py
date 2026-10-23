import hmac
import json
import os
import socket
import subprocess
import sys
import threading
import time
from email.utils import formatdate
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import yaml

# Ensure the parent directory is in the import path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from camera_hub import CameraHub
from config import load_teams
from control_lock import ControlLock
from gc_client import PENALTY_NAMES, SET_PLAY_NAMES, GCReceiver
from session import EventLog, Recorder
from sim_gc import SimGameController
from socket_client import UDPReceiver
from tv_program import TVProgram

_STATIC_TYPES = {
    ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm",
    ".css": "text/css", ".json": "application/json", ".xml": "application/xml",
    ".txt": "text/plain", ".png": "image/png", ".map": "application/json",
}


class _HTTPServer(ThreadingHTTPServer):
    # Default listen backlog is 5: 20 parallel /state requests waited up to 2.9 s.
    request_queue_size = 64
    daemon_threads = True


class ControlServer:
    def __init__(self, config_path=None):
        if config_path is None:
            # Look for config.yaml in workspace parent of src/
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")

        print(f"[ControlServer] Loading config from {config_path}")
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        # Port and Host configurations
        self.http_port = 8080
        self.tcm_port = self.config.get("socket", {}).get("port", 10006)
        self.tcm_host = self.config.get("socket", {}).get("host", "0.0.0.0")

        self.gc_port = self.config.get("game_controller", {}).get("port", 3838)
        self.gc_host = self.config.get("game_controller", {}).get("host", "0.0.0.0")
        self.own_team = self.config.get("game_controller", {}).get("own_team", 19)

        # Drawings filtering
        self.ignored_paths = self.config.get("drawings", {}).get("ignored_paths", [])
        self.disabled_drawings_str = ""
        # (operator name, time) of the last manual command that used the referee-rules bypass; /state "bypass" shows it
        self.bypass_by = ("", 0.0)

        # Receivers
        # Robots report in their own team's frame; this team colour is mirrored into the shared field frame.
        mirror_color = self.config.get("frames", {}).get("mirror_team_color", "blue")
        self.udp_receiver = UDPReceiver(self.tcm_host, self.tcm_port, mirror_color=mirror_color)
        # Hosted sessions (oraculum/hosted): ORACULUM_SIM_GC="<team A>,<team B>" runs the simulated referee, which sends
        # to the robot on 127.0.0.1:3838; the gateway's receiver then must not take 3838, so it binds a free port.
        sim_teams = [t for t in os.environ.get("ORACULUM_SIM_GC", "").split(",") if t.strip().isdigit()]
        if sim_teams:
            self.gc_host, self.gc_port = "127.0.0.1", 0
        self.gc_receiver = GCReceiver(host=self.gc_host, port=self.gc_port, own_team=self.own_team)
        # ORACULUM_GC_TARGETS (comma-separated IPs): send the referee to each robot's own loopback IP. With many
        # robots isolated in network namespaces, one 127.0.0.1:3838 reaches only one; default stays single-target.
        gc_ips = [ip.strip() for ip in os.environ.get("ORACULUM_GC_TARGETS", "").split(",") if ip.strip()]
        gc_targets = [(ip, 3838) for ip in gc_ips] if gc_ips else (("127.0.0.1", 3838),)
        self.sim_gc = SimGameController(self.gc_receiver, teams=sim_teams, targets=gc_targets) if len(sim_teams) == 2 else None

        # Session recording + event log (src/session.py), robot camera relay (src/camera_hub.py)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.recorder = Recorder(os.path.join(root, "recordings"))
        self.udp_receiver.recorder = self.recorder
        self.gc_receiver.on_packet = self.recorder.write_gc
        self.events = EventLog(self.udp_receiver, self.gc_receiver, self.recorder)
        self.recorder.on_stop = lambda reason: self.events.add("REC", "gateway", f"recording stopped: {reason}")
        self.camera_hub = CameraHub(port=self.config.get("camera", {}).get("port", 10009))
        # Public TV view (src/tv.html) and director console (src/director.html): one program, POST /tv changes it
        self.tv = TVProgram()
        teams = load_teams(root)
        self.team_names = {str(n): t["name"] for n, t in teams.items()}  # config/teams.yaml (19 -> "SPQR")
        # Scoreboard logos: src/static/logos/<number>.png (the TCM's file names), or a team's `logo:` in teams.yaml
        logo_dir = os.path.join(root, "src", "static", "logos")
        files = set(os.listdir(logo_dir)) if os.path.isdir(logo_dir) else set()
        logos = {f[:-4]: f for f in files if f.endswith(".png") and f[:-4].isdigit()}
        logos.update({str(n): t["logo"] for n, t in teams.items() if t["logo"] in files})
        self.team_logos = {n: f"/static/logos/{f}" for n, f in logos.items()}  # GET /tv; a team without a file: none

        # GET /field: the field of config.yaml (fields/*.yaml, metres), for the 2D view and the camera overlay
        with open(os.path.join(root, "fields", self.config.get("field", "fieldAdultSize.yaml"))) as f:
            self.field = yaml.safe_load(f)

        # Fleet table: a robot's version is "current" when its commit equals HEAD of this checkout
        self.fleet_repo = os.path.normpath(os.path.join(root, self.config.get("fleet", {}).get("repo", "../spqrbooster2026")))
        self._head = (0.0, "")

        # Hosted sessions: with ORACULUM_ACCESS_TOKEN set, every request needs the token (?token= once, then a cookie).
        self.access_token = os.environ.get("ORACULUM_ACCESS_TOKEN", "")
        # Hosted session: every joystick datagram goes to this address, whatever the body says (no UDP to the internet).
        self.control_ip = os.environ.get("ORACULUM_CONTROL_IP", "")
        self.control_lock = ControlLock()  # engineer mode: one operator drives at a time (src/control_lock.py)
        self.boot = round(time.time())  # in /state: a page sees a gateway restart (event ids begin at 1 again)

        self.http_server = None

    # POST /stop kinds: joystick datagram fields as LowControlBridge (spqrbooster2026) reads them
    STOP_FIELDS = {"stop": {"isManual": True, "stop": True},          # stand in the Prep pose until Play/Manual
                   "lie": {"isManual": True, "lie": True},            # the firmware lays the robot on its back
                   "damp": {"isManual": True, "damp": True},          # motors soft: the robot FALLS (can break it)
                   "resume": {"isManual": True, "rb": True, "rt": True, "a": True}}  # Play combo: clears both

    def send_joystick(self, ips, fields: dict, repeat: int = 3) -> None:
        """Joystick datagrams to UDP 10007 of each robot (ORACULUM_CONTROL_IP replaces the address when set),
        `repeat` times 0.1 s apart in a thread: one lost datagram must not lose a STOP."""
        data = json.dumps(fields).encode("utf-8")
        targets = {(self.control_ip or ip, 10007) for ip in ips}

        def run():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for i in range(repeat):
                    for target in targets:
                        try:
                            sock.sendto(data, target)
                        except OSError as exc:
                            print(f"[stop] {target}: {exc}")
                    time.sleep(0.1)

        threading.Thread(target=run, daemon=True, name="send_joystick").start()

    def git_head(self) -> str:
        """Short commit of the robot code checkout (what `pixi run deploy` would install), refreshed every 30 s."""
        t, head = self._head
        if time.time() - t > 30:
            try:
                head = subprocess.run(["git", "-C", self.fleet_repo, "rev-parse", "--short=8", "HEAD"],
                                      capture_output=True, text=True, timeout=5).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                head = ""
            self._head = (time.time(), head)
        return head

    def start(self):
        # Start background network receivers
        self.udp_receiver.start()
        self.gc_receiver.start()
        self.events.start()
        self.camera_hub.start()
        if self.sim_gc:
            self.sim_gc.start()

        # Start HTTP server
        server_address = ("", self.http_port)
        server_instance = self

        class CommandHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # Suppress output logs to keep the console clean
                pass

            def _allowed(self):
                """Access token check (hosted sessions); True without ORACULUM_ACCESS_TOKEN. Sends 401 itself."""
                token = server_instance.access_token
                if not token:
                    return True
                given = parse_qs(urlparse(self.path).query).get("token", [""])[0]
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                if hmac.compare_digest(given, token) or ("oraculum_token" in cookie and hmac.compare_digest(cookie["oraculum_token"].value, token)):
                    self._set_cookie = given == token
                    return True
                body = b"This oraculum session needs its access link."
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return False

            def end_headers(self):
                if getattr(self, "_set_cookie", False):  # first visit with ?token=: keep it for the page's own requests
                    self.send_header("Set-Cookie", f"oraculum_token={server_instance.access_token}; Path=/; HttpOnly; SameSite=Lax")  # no Secure: field laptops serve plain HTTP
                    self._set_cookie = False
                super().end_headers()

            def _json(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8") or "{}")

            def do_GET(self):
                if not self._allowed():
                    return
                parsed_path = urlparse(self.path)
                query = parse_qs(parsed_path.query)
                if parsed_path.path == "/field":
                    self._json(200, server_instance.field)
                    return
                if parsed_path.path == "/events":
                    since = int(query.get("since", ["0"])[0] or 0)
                    self._json(200, {"events": server_instance.events.since(since), "ids": server_instance.events.ids()})
                    return
                if parsed_path.path == "/recordings":
                    self._json(200, {"recordings": server_instance.recorder.list(), "running": server_instance.recorder.status()})
                    return
                if parsed_path.path.startswith("/recordings/"):
                    name = parsed_path.path.rsplit("/", 1)[1]
                    names = {r["name"] + ".jsonl" for r in server_instance.recorder.list()}
                    if name not in names:  # only listed files: no path from the URL reaches the disk
                        self._json(404, {"error": "no such recording"})
                        return
                    path = os.path.join(server_instance.recorder.folder, name)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                    self.send_header("Content-Length", str(os.path.getsize(path)))
                    self.end_headers()
                    with open(path, "rb") as f:
                        while chunk := f.read(1 << 16):
                            self.wfile.write(chunk)
                    return
                if parsed_path.path == "/camera":
                    ip, _, rid = query.get("robot", [""])[0].rpartition("|")
                    if not ip or not rid.lstrip("-").isdigit():
                        self._json(400, {"error": "robot=<ip>|<id> expected"})
                        return
                    state = server_instance.udp_receiver.latest()
                    agent = next((a for a in (state.agents if state else []) if a.ip == ip and a.id == int(rid)), None)
                    # Only robots that send telemetry get a request: the query cannot aim UDP at other hosts.
                    if agent is not None:
                        server_instance.camera_hub.request(ip, int(rid))
                    frame = server_instance.camera_hub.latest(ip, int(rid))
                    T = frame["meta"].get("T") if frame else None
                    mirror = server_instance.udp_receiver.mirror_color
                    if agent is not None and mirror and str(agent.color).lower() == mirror and isinstance(T, list) and len(T) == 16:
                        # Same point mirror as the poses (socket_client.mirror_packet): negate the field x and y rows.
                        frame["meta"]["T"] = [-v for v in T[:8]] + T[8:]
                    self._json(200, frame or {"status": "waiting"})
                    return
                if parsed_path.path == "/tv":  # the TV program plus team names and logos (the page itself is /tv.html)
                    self._json(200, {**server_instance.tv.view(), "team_names": server_instance.team_names,
                                     "team_logos": server_instance.team_logos})
                    return
                if parsed_path.path == "/state":
                    client = query.get("client", [""])[0]
                    server_instance.control_lock.seen(client)
                    latest_state = server_instance.udp_receiver.latest()
                    state_dict = (
                        latest_state.to_dict()
                        if latest_state
                        else {"agents": [], "ball": None, "drawings": [], "texts": []}
                    )

                    # Filter drawings based on ignored paths and dynamic selection
                    if "drawings" in state_dict and state_dict["drawings"]:
                        disabled_str = server_instance.disabled_drawings_str
                        disabled = disabled_str.split(",") if disabled_str else []
                        state_dict["drawings"] = [
                            dr for dr in state_dict["drawings"]
                            if dr.get("path") not in server_instance.ignored_paths and dr.get("path") not in disabled
                        ]

                    # Merge GameController state if available
                    gc_data = server_instance.gc_receiver.latest()
                    if gc_data:
                        state_dict["gamecontroller"] = {
                            "state": gc_data.state_name,
                            "secsRemaining": gc_data.secs_remaining if hasattr(gc_data, 'secs_remaining') else getattr(gc_data, 'secsRemaining', 0),
                            "kickingTeam": gc_data.kicking_team if hasattr(gc_data, 'kicking_team') else getattr(gc_data, 'kickingTeam', 0),
                            "score": [t.score for t in gc_data.teams] if hasattr(gc_data, 'teams') else [0, 0],
                            "message_budget": [t.message_budget for t in gc_data.teams] if hasattr(gc_data, 'teams') else [12000, 12000],
                            "own_team_index": gc_data.own_team_index if hasattr(gc_data, 'own_team_index') else -1,
                            "external_gc_online": server_instance.gc_receiver.external_gc_online,
                            "teams": [t.team_number for t in gc_data.teams], "first_half": gc_data.first_half,
                            # jersey colour per team (GameController TEAM_BLUE=0 ... TEAM_GRAY=9): the TV bar before any robot sends
                            "colors": [("blue", "red", "yellow", "black", "white", "green", "orange", "purple", "brown", "gray")[t.field_player_colour]
                                       if t.field_player_colour < 10 else "" for t in gc_data.teams],
                            "set_play": gc_data.set_play, "sim": server_instance.sim_gc is not None,
                            "set_play_name": SET_PLAY_NAMES.get(gc_data.set_play, ""), "secondary_time": gc_data.secondary_time,
                            "phase": gc_data.phase_name, "age": round(time.time() - server_instance.gc_receiver.last_packet_time, 1),
                            "source": "simulated referee" if server_instance.sim_gc else getattr(server_instance.gc_receiver, "last_sender", ""),
                            # penalised players only: {team number: {player number: [penalty name, seconds left]}}
                            "penalties": {str(t.team_number): {str(i + 1): [PENALTY_NAMES.get(p.penalty, str(p.penalty)), p.secs_till_unpenalised]
                                                               for i, p in enumerate(t.players) if p.penalty}
                                          for t in gc_data.teams},
                        }
                    else:
                        state_dict["gamecontroller"] = {
                            "external_gc_online": server_instance.gc_receiver.external_gc_online
                        }

                    state_dict["fleet"] = {"head": server_instance.git_head(), "link": server_instance.udp_receiver.link_stats()}
                    state_dict["rec"] = server_instance.recorder.status()
                    state_dict["lock"] = server_instance.control_lock.view(client)
                    state_dict["boot"] = server_instance.boot
                    name, t = server_instance.bypass_by  # every page shows who drives with the bypass (last 5 s)
                    state_dict["bypass"] = name if time.time() - t < 5 else ""
                    ids = server_instance.events.ids()
                    state_dict["last_event"] = ids[-1] if ids else 0
                    state_dict["tv"] = server_instance.tv.view()
                    state_dict["restart"] = bool(os.environ.get("ORACULUM_RESTART_CMD"))  # hosted: POST /session_restart exists

                    response = json.dumps(state_dict).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                elif parsed_path.path in ("/", "/index.html", "/wasm_test.html", "/dashboard", "/dashboard.html", "/ar_dashboard.html",
                                          "/fleet", "/fleet.html", "/robot", "/robot.html",
                                          "/tv.html", "/director", "/director.html"):
                    try:
                        filename = os.path.basename(parsed_path.path)
                        if not filename or filename == "/":
                            filename = "index.html"
                        elif filename in ("dashboard", "fleet", "robot", "director"):
                            filename += ".html"
                            
                        dashboard_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), filename
                        )
                        if not os.path.exists(dashboard_path):
                            dashboard_path = os.path.join(
                                os.path.dirname(os.path.abspath(__file__)), "index.html"
                            )
                        with open(dashboard_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        
                        response = content.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(response)))
                        self.end_headers()
                        self.wfile.write(response)
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode("utf-8"))
                elif parsed_path.path.startswith("/static/"):
                    try:
                        static_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
                        static_path = os.path.normpath(os.path.join(static_root, unquote(parsed_path.path[len("/static/"):])))
                        # Subfolders are allowed (mujoco/, models/); anything outside static/ is not.
                        if static_path.startswith(static_root + os.sep) and os.path.isfile(static_path):
                            # no-cache + Last-Modified: the browser asks every time and gets a 304 without a body
                            # while the file is unchanged. The big WASM and scene files download once, a new
                            # renderer or scene shows on the next load, and b2_engine.js and .wasm never come
                            # from two different builds. ponytail: browsers echo Last-Modified, so string equality.
                            last_modified = formatdate(os.stat(static_path).st_mtime, usegmt=True)
                            if self.headers.get("If-Modified-Since") == last_modified:
                                self.send_response(304)
                                self.send_header("Last-Modified", last_modified)
                                self.send_header("Cache-Control", "no-cache")
                                self.end_headers()
                                return
                            with open(static_path, "rb") as f:
                                response = f.read()

                            ext = os.path.splitext(static_path)[1].lower()
                            content_type = _STATIC_TYPES.get(ext, "application/octet-stream")

                            self.send_response(200)
                            self.send_header("Content-Type", content_type)
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.send_header("Content-Length", str(len(response)))
                            self.send_header("Last-Modified", last_modified)
                            self.send_header("Cache-Control", "no-cache")
                            self.end_headers()
                            self.wfile.write(response)
                        else:
                            self.send_response(404)
                            self.end_headers()
                    except Exception as e:
                        self.send_response(500)
                        self.end_headers()
                        self.wfile.write(str(e).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if not self._allowed():
                    return
                parsed_path = urlparse(self.path)
                if parsed_path.path == "/gc":  # simulated referee of a hosted session
                    if server_instance.sim_gc is None:
                        self._json(404, {"error": "no simulated GameController (set ORACULUM_SIM_GC)"})
                        return
                    try:
                        cmd = self._body()
                        status = server_instance.sim_gc.set(state=cmd.get("state"), kicking_team=cmd.get("kicking_team"),
                                                            goal=cmd.get("goal"), half=cmd.get("half"), penalty=cmd.get("penalty"))
                    except (ValueError, TypeError, KeyError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    server_instance.events.add("REFEREE", "manual", f"referee: {status['state']}, score {status['scores'][0]}-{status['scores'][1]}")
                    self._json(200, status)
                    return
                if parsed_path.path == "/session_restart":  # hosted session: robots, ball and referee back to the start
                    cmd = os.environ.get("ORACULUM_RESTART_CMD", "")
                    if not cmd:
                        self._json(404, {"error": "no session restart here (ORACULUM_RESTART_CMD is not set)"})
                        return
                    server_instance.events.add("SESSION", "", "session restart requested")
                    self._json(202, {"status": "restarting", "seconds": 60})
                    # ponytail: the command (systemctl --no-block restart ...) also ends this gateway; the reply goes first
                    threading.Timer(0.5, subprocess.Popen, args=(cmd,), kwargs={"shell": True}).start()
                    return
                if parsed_path.path in ("/stop", "/control_lock"):
                    try:
                        cmd = self._body()
                    except (ValueError, TypeError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    client, name = str(cmd.get("client", "")), str(cmd.get("name", ""))[:40]
                    lock = server_instance.control_lock
                    if parsed_path.path == "/control_lock":
                        action = cmd.get("action")
                        if not client or action not in ("take", "release", "grant", "deny"):
                            self._json(400, {"error": "expected {action: take|release|grant|deny, client, name}"})
                            return
                        before = lock.holder_name()
                        if action == "take":
                            result = lock.take(client, name)
                        elif action == "release":
                            lock.release(client)
                            result = "released"
                        else:
                            result = "ok" if lock.answer(client, action == "grant") else "nothing to answer"
                        if lock.holder_name() != before:
                            server_instance.events.add("CONTROL", "manual", f"control: {lock.holder_name() or 'free'} (was {before or 'free'})")
                        self._json(200, {"result": result, "lock": lock.view(client)})
                        return
                    # POST /stop {robot: <ip>|"all", kind: stop|lie|damp|resume}: STOP, LIE and DAMP need no lock and
                    # pass the GameController rule; resume (the Play combo) is a normal command and needs the lock.
                    kind = cmd.get("kind", "stop")
                    if kind not in server_instance.STOP_FIELDS:
                        self._json(400, {"error": "kind must be stop, lie, damp or resume"})
                        return
                    # DAMP drops the robot and can break it: one robot at a time, and only with confirm = its address
                    if kind == "damp" and (cmd.get("robot", "all") == "all" or cmd.get("confirm") != cmd.get("robot")):
                        self._json(400, {"error": "DAMP needs one robot and confirm = its address (never all robots)"})
                        return
                    link = server_instance.udp_receiver.link_stats()
                    robot = str(cmd.get("robot", "all"))
                    # "all": every robot heard in the last 60 s (the fleet page's offline window), so a Wi-Fi gap
                    # does not skip one; one robot: only an address that sent telemetry (no UDP to other hosts)
                    targets = sorted(ip for ip, st in link.items() if st["age"] < 60) if robot == "all" else [robot] if robot in link else []
                    state = server_instance.udp_receiver.latest()
                    # oraculum: match robots send telemetry only and do not listen on UDP 10007 (HSL: robots are autonomous)
                    telemetry_only = {a.ip for a in (state.agents if state else []) if a.sys.get("link") == "telemetry"}
                    if targets and set(targets) <= telemetry_only:
                        self._json(409, {"error": "This robot is in match mode (oraculum: match): it sends telemetry only and "
                                                  "takes no command. Use the referee or the robot's own buttons.",
                                         "telemetry_only": sorted(telemetry_only)})
                        return
                    targets = [ip for ip in targets if ip not in telemetry_only]
                    if not targets and robot != "all" and robot not in link:  # a typo or an old IP: say which address
                        self._json(409, {"error": f"No robot with IP {robot} sends telemetry to this oraculum."})
                        return
                    if not targets:
                        self._json(409, {"error": "No robot reached: none sends telemetry to this oraculum. A robot sends "
                                                  "telemetry and listens on UDP 10007 only with oraculum: practice, or with "
                                                  "useRerun: true (deploy.yaml)."})
                        return
                    fields = dict(server_instance.STOP_FIELDS[kind])
                    if kind == "stop" and robot != "all":
                        fields["undamp"] = True  # STOP for one robot also ends its DAMP (it stands); STOP ALL never does
                    if kind == "resume":  # a damped robot cannot walk (the firmware refuses Damping -> Walking)
                        damped = {a.ip for a in (state.agents if state else []) if a.latch == "damp"}
                        if damped & set(targets) == set(targets):
                            self._json(409, {"error": "This robot is damped: lift it, press its own STOP (it stands in the "
                                                      "Prep pose), then Resume.", "damped": sorted(damped)})
                            return
                        targets = [ip for ip in targets if ip not in damped]
                        if not lock.acquire_for_command(client, name):
                            h = lock.holder_name()  # free but refused: this client released control just now
                            self._json(423, {"error": f"{h} has control. Ask for it first." if h else "You released control. Press Take in the header first.", "holder": h})
                            return
                    server_instance.send_joystick(targets, fields)
                    names = {}
                    for a in (state.agents if state else []):  # one address can carry several simulated robots
                        rn = f"T{a.team or '?'} R{a.id}"
                        names[a.ip] = f"{names[a.ip]}, {rn}" if a.ip in names else rn
                    labels = [f"{names.get(ip, '?')} ({ip})" for ip in targets]
                    server_instance.events.add(kind.upper(), "manual", f"{kind.upper()} → {', '.join(labels)}" + (f" by {name}" if name else ""),
                                               names.get(targets[0], "") if len(targets) == 1 else "")
                    self._json(200, {"status": "sent", "kind": kind, "targets": targets, "names": labels})
                    return
                if parsed_path.path == "/tv":  # TV program (src/tv_program.py); no control lock: it moves no robot
                    try:
                        cmd = self._body()
                    except (ValueError, TypeError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    state = server_instance.udp_receiver.latest()
                    live = {f"{a.ip}|{a.id}" for a in (state.agents if state else [])}
                    self._json(*server_instance.tv.update(cmd, live))
                    return
                if parsed_path.path in ("/events", "/record"):
                    try:
                        cmd = self._body()
                    except (ValueError, TypeError) as e:
                        self._json(400, {"error": str(e)})
                        return
                    if parsed_path.path == "/record":
                        # {on: true, by}: start (a running recording is returned, not restarted); {on: false, name}:
                        # stop exactly that recording, so a stale page cannot stop someone else's new one
                        rec = server_instance.recorder
                        status = rec.status()
                        by = str(cmd.get("by", ""))[:40] or self.client_address[0]
                        if cmd.get("on"):
                            if not status["on"]:
                                name = rec.start(by)
                                server_instance.events.add("REC", "manual", f"recording started: {name} by {by}")
                        elif status["on"]:
                            if cmd.get("name") != status["name"]:
                                self._json(409, {"error": f"{status['name']} is running, not {cmd.get('name')}", **status})
                                return
                            rec.stop()
                            server_instance.events.add("REC", "manual", f"recording stopped: {status['name']}.jsonl, "
                                                       f"{status['secs']:.0f} s, {status['bytes'] / 1e6:.1f} MB (started by {status['by']}, stopped by {by})")
                        self._json(200, rec.status())
                    elif "delete" in cmd:
                        self._json(200, {"deleted": server_instance.events.delete(int(cmd["delete"]))})
                    elif isinstance(cmd.get("add"), dict):
                        add = cmd["add"]
                        text = str(add.get("text", "")).strip()[:200] or "mark"
                        self._json(200, server_instance.events.add("MARK", "manual", text, str(add.get("robot", ""))[:40]))
                    else:
                        self._json(400, {"error": "expected {add: {text, robot}} or {delete: id}"})
                    return
                if parsed_path.path == "/control":
                    content_length = int(self.headers["Content-Length"])
                    post_data = self.rfile.read(content_length)
                    try:
                        cmd = json.loads(post_data.decode("utf-8"))
                        target_ip = server_instance.control_ip or cmd.get("ip", "127.0.0.1")
                        target_port = cmd.get("port", 10007)

                        # Read all control input fields (both joystick structure and legacy velocity fields)
                        if "disabled_drawings" in cmd:
                            disabled_drawings = cmd.get("disabled_drawings", "")
                            server_instance.disabled_drawings_str = disabled_drawings
                        else:
                            disabled_drawings = server_instance.disabled_drawings_str

                        # Only an explicit manual command reaches the robot: a filter-only body
                        # or isManual false/missing stops here (no UDP datagram).
                        if cmd.get("isManual") is not True:
                            self.send_response(200)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()
                            reply = {"status": "ok"} if set(cmd) <= {"disabled_drawings"} else {
                                "status": "ignored", "reason": "isManual is not true; nothing sent to the robot"}
                            self.wfile.write(json.dumps(reply).encode("utf-8"))
                            return

                        # Engineer mode: a manual command needs the control lock (a free lock is taken here)
                        lock = server_instance.control_lock
                        before = lock.holder_name()
                        granted = lock.acquire_for_command(str(cmd.get("client", "")), str(cmd.get("operator", ""))[:40])
                        if granted and not before:  # a free lock taken by the first command: log it like a Take
                            server_instance.events.add("CONTROL", "manual", f"control: {lock.holder_name()} (was free)")
                        if not granted:
                            holder = lock.holder_name()
                            self._json(423, {"status": "locked", "holder": holder,
                                             "reason": f"{holder} has control. Ask for it." if holder
                                             else "You released control. Press Take in the header first." if cmd.get("client")
                                             else "client id missing: reload the page"})
                            return

                        payload = {
                            "vx": cmd.get("vx", 0.0),
                            "vy": cmd.get("vy", 0.0),
                            "vtheta": cmd.get("vtheta", 0.0),
                            "isManual": cmd.get("isManual", False),
                            "lt": cmd.get("lt", False),
                            
                            # Raw sticks in the Booster remote convention, as main's Manual.cpp reads them:
                            # vx = -ly*maxVx, vy = -lx*maxVy, vyaw = -rx*maxVyaw (stick up = ly < 0 = forward).
                            "lx": cmd.get("lx", -cmd.get("vy", 0.0)),
                            "ly": cmd.get("ly", -cmd.get("vx", 0.0)),
                            "rx": cmd.get("rx", -cmd.get("vtheta", 0.0)),
                            "ry": cmd.get("ry", 0.0),
                            
                            # Joystick face buttons
                            "a": cmd.get("a", False),
                            "b": cmd.get("b", False),
                            "x": cmd.get("x", False),
                            "y": cmd.get("y", False),
                            
                            # Joystick shoulder/triggers
                            "lb": cmd.get("lb", False),
                            "rb": cmd.get("rb", False),
                            # lt mapped above
                            "rt": cmd.get("rt", False),
                            
                            # Stick clicks
                            "ls": cmd.get("ls", False),
                            "rs": cmd.get("rs", False),
                            
                            # Menu buttons
                            "back": cmd.get("back", False),
                            "start": cmd.get("start", False),
                            
                            # D-pad
                            "hat_c": cmd.get("hat_c", False),
                            "hat_u": cmd.get("hat_u", False),
                            "hat_d": cmd.get("hat_d", False),
                            "hat_l": cmd.get("hat_l", False),
                            "hat_r": cmd.get("hat_r", False),
                            "hat_lu": cmd.get("hat_lu", False),
                            "hat_ld": cmd.get("hat_ld", False),
                            "hat_ru": cmd.get("hat_ru", False),
                            "hat_rd": cmd.get("hat_rd", False),
                            
                            # Dynamic drawing stream filters
                            "disabled_drawings": disabled_drawings
                        }

                        # Check GameController state rules
                        gc_data = server_instance.gc_receiver.latest()
                        is_active_play = False
                        gc_state_name = "UNKNOWN"
                        if gc_data:
                            gc_state_name = gc_data.state_name
                            if gc_data.state in (1, 2, 3):  # READY, SET, PLAYING
                                is_active_play = True

                        testing_override = cmd.get("testingOverride", False) or cmd.get("bypassRules", False)

                        # Every body that gets here is a manual command (isManual is true)
                        if is_active_play and not testing_override:
                            self.send_response(403)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                "status": "blocked",
                                "reason": f"Manual override blocked during active game state ({gc_state_name}). Enable testing override to bypass."
                            }).encode("utf-8"))
                            return

                        if testing_override:
                            server_instance.bypass_by = (lock.holder_name() or "an operator", time.time())

                        # Send UDP control payload to robot
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        if target_ip == "255.255.255.255":
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        sock.sendto(json.dumps(payload).encode("utf-8"), (target_ip, target_port))
                        sock.close()

                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                    except Exception as e:
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()

        # Threaded: a phone that downloads the 10 MB WASM file must not block /state for other clients.
        self.http_server = _HTTPServer(server_address, CommandHandler)
        print(f"[ControlServer] Listening on HTTP port {self.http_port} (API routes: /state, /control, /events, /record, /camera, /tv)")
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()

    def stop(self):
        if self.http_server:
            self.http_server.shutdown()
        self.udp_receiver.stop()
        self.gc_receiver.stop()
        self.events.stop()
        self.camera_hub.stop()
        if self.sim_gc:
            self.sim_gc.stop()
        self.recorder.stop()
        print("[ControlServer] Stopped background services.")


if __name__ == "__main__":
    server = ControlServer()
    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.stop()
