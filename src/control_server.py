import sys
import os
import json
import socket
import threading
import time
import yaml
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# Ensure the parent directory is in the import path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from socket_client import UDPReceiver
from gc_client import GCReceiver


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

        # Receivers
        self.udp_receiver = UDPReceiver(self.tcm_host, self.tcm_port)
        self.gc_receiver = GCReceiver(host=self.gc_host, port=self.gc_port, own_team=self.own_team)

        self.http_server = None

    def start(self):
        # Start background network receivers
        self.udp_receiver.start()
        self.gc_receiver.start()

        # Start HTTP server
        server_address = ("", self.http_port)
        server_instance = self

        class CommandHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # Suppress output logs to keep the console clean
                pass

            def do_GET(self):
                parsed_path = urlparse(self.path)
                if parsed_path.path == "/state":
                    # Merged status state
                    latest_state = server_instance.udp_receiver.latest()
                    state_dict = (
                        latest_state.to_dict()
                        if latest_state
                        else {"agents": [], "ball": None, "drawings": [], "texts": []}
                    )

                    # Filter drawings based on ignored paths and dynamic selection
                    if "drawings" in state_dict and state_dict["drawings"]:
                        state_dict["drawings"] = [
                            dr for dr in state_dict["drawings"]
                            if dr.get("path") not in server_instance.ignored_paths and
                            (not server_instance.disabled_drawings_str or f",{dr.get('path')}," not in server_instance.disabled_drawings_str)
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
                            "external_gc_online": server_instance.gc_receiver.external_gc_online
                        }
                    else:
                        state_dict["gamecontroller"] = {
                            "external_gc_online": server_instance.gc_receiver.external_gc_online
                        }

                    response = json.dumps(state_dict).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                elif parsed_path.path in ("/", "/index.html", "/dashboard"):
                    try:
                        dashboard_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), "web_dashboard.html"
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
                elif parsed_path.path in ("/ar", "/ar.html", "/ar_dashboard.html"):
                    try:
                        dashboard_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), "ar_dashboard.html"
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
                        filename = os.path.basename(parsed_path.path)
                        static_path = os.path.join(
                            os.path.dirname(os.path.abspath(__file__)), "static", filename
                        )
                        if os.path.exists(static_path):
                            with open(static_path, "rb") as f:
                                response = f.read()
                            
                            content_type = "application/javascript" if filename.endswith(".js") else "application/octet-stream"
                            self.send_response(200)
                            self.send_header("Content-Type", content_type)
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.send_header("Content-Length", str(len(response)))
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
                parsed_path = urlparse(self.path)
                if parsed_path.path == "/control":
                    content_length = int(self.headers["Content-Length"])
                    post_data = self.rfile.read(content_length)
                    try:
                        cmd = json.loads(post_data.decode("utf-8"))
                        target_ip = cmd.get("ip", "127.0.0.1")
                        target_port = cmd.get("port", 10007)

                        # Read all control input fields (both joystick structure and legacy velocity fields)
                        if "disabled_drawings" in cmd:
                            disabled_drawings = cmd.get("disabled_drawings", "")
                            server_instance.disabled_drawings_str = disabled_drawings
                        else:
                            disabled_drawings = server_instance.disabled_drawings_str

                        payload = {
                            "vx": cmd.get("vx", 0.0),
                            "vy": cmd.get("vy", 0.0),
                            "vtheta": cmd.get("vtheta", 0.0),
                            "isManual": cmd.get("isManual", False),
                            "lt": cmd.get("lt", False),
                            
                            # Joystick mapping matching Joystick.h / Bridge.cpp
                            "lx": cmd.get("lx", cmd.get("vy", 0.0)),
                            "ly": cmd.get("ly", cmd.get("vx", 0.0)),
                            "rx": cmd.get("rx", cmd.get("vtheta", 0.0)),
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
                        
                        # Command is manual control if the joystick is active or isManual is true
                        is_manual_override = payload["isManual"] or abs(payload["lx"]) > 0.01 or abs(payload["ly"]) > 0.01 or abs(payload["rx"]) > 0.01

                        if is_active_play and is_manual_override and not testing_override:
                            self.send_response(403)
                            self.send_header("Content-Type", "application/json")
                            self.send_header("Access-Control-Allow-Origin", "*")
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                "status": "blocked",
                                "reason": f"Manual override blocked during active game state ({gc_state_name}). Enable testing override to bypass."
                            }).encode("utf-8"))
                            return

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

        self.http_server = HTTPServer(server_address, CommandHandler)
        print(f"[ControlServer] Listening on HTTP port {self.http_port} (API routes: /state, /control)")
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()

    def stop(self):
        if self.http_server:
            self.http_server.shutdown()
        self.udp_receiver.stop()
        self.gc_receiver.stop()
        print("[ControlServer] Stopped background services.")


if __name__ == "__main__":
    server = ControlServer()
    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.stop()
