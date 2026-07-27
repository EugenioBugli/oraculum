#!/usr/bin/env python3
"""
Rerun .rrd Log & Telemetry Replay Bridge for Oraculum
Reads recorded .rrd or JSON telemetry log files and streams them frame-by-frame over UDP port 10006.
"""

import sys
import os
import time
import json
import math
import socket
import argparse

def replay_telemetry(log_file, target_host="127.0.0.1", target_port=10006, fps=30):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / fps
    print(f"[*] Replaying telemetry log from '{log_file}' to {target_host}:{target_port} at {fps} FPS...")

    try:
        with open(log_file, "r") as f:
            lines = f.readlines()
        
        print(f"[*] Loaded {len(lines)} frames from {log_file}.")
        frame_idx = 0
        while True:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                sock.sendto(line.encode('utf-8'), (target_host, target_port))
                frame_idx += 1
                if frame_idx % 100 == 0:
                    print(f"[*] Replayed frame {frame_idx}/{len(lines)}...")
                time.sleep(interval)
            print("[*] Replay loop completed. Restarting from start...")
    except KeyboardInterrupt:
        print("\n[*] Replay stopped by user.")
    except Exception as e:
        print(f"[!] Replay error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay telemetry or Rerun log files to Oraculum.")
    parser.add_argument("log_file", nargs="?", default="", help="Path to .json or .rrd log file.")
    parser.add_argument("--fps", type=int, default=30, help="Replay frame rate (default: 30)")
    args = parser.parse_args()

    if not args.log_file or not os.path.exists(args.log_file):
        print("[!] Log file not specified or not found. Generating sample match log for replay...")
        sample_log = "/tmp/sample_match_replay.json"
        with open(sample_log, "w") as f:
            for i in range(150):
                t = i * 0.05
                data = {
                    "agents": [
                        {"id": 1, "x": 1.0 + 2.0 * math.cos(t), "y": 0.5 * math.sin(t), "angle": t, "team": 19},
                        {"id": 2, "x": -7.5, "y": 0.2 * math.cos(t), "angle": 0.0, "team": 19},
                        {"id": 3, "x": -3.0 + 1.0 * math.sin(t*0.5), "y": -2.0, "angle": 0.5, "team": 51}
                    ],
                    "ball": {"x": 2.0 + 2.0 * math.cos(t), "y": 0.5 * math.sin(t), "z": 0.04},
                    "drawings": [
                        {"type": "circle", "path": "/field/center_circle", "coords": [0, 0], "size": 0.75, "color": [0, 229, 255]},
                        {"type": "line", "path": "/coordination/pass_line", "coords": [1.0 + 2.0 * math.cos(t), 0.5 * math.sin(t), 2.0 + 2.0 * math.cos(t), 0.5 * math.sin(t)], "size": 3, "color": [124, 77, 255]}
                    ]
                }
                f.write(json.dumps(data) + "\n")
        args.log_file = sample_log

    replay_telemetry(args.log_file, fps=args.fps)
