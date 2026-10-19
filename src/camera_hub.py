"""Robot camera relay of the oraculum gateway.

A robot sends camera frames only on request, so the Wi-Fi carries images only for the robots a page shows:
  1. A page polls GET /camera?robot=<ip>|<id>. The gateway sends at most once per second
     {"camera": true, "id": <id>, "port": 10009} to <ip>:10008 (DebugCameraSender on the robot).
  2. For 3 s after each request the robot sends frames to <gateway>:10009, a few per second. One frame is one
     datagram: b"OCAM" + JSON header + b"\\n" + JPEG. Header fields:
       id, team, color      the robot
       w, h                 size of the JPEG in pixels
       K [fx, fy, cx, cy]   camera intrinsics for that size
       T [16 floats]        camera-to-field transform, row-major 4x4, in the robot's own team frame
                            (camera axes: x right, y down, z forward); the field lines drawn with it show
                            whether the robot's pose and camera model agree with the image
       det [[class name, conf, x, y, w, h], ...]   detections, (x, y) = top left, JPEG pixels
       ts                   capture time, ns
  3. The gateway keeps the newest frame per robot; GET /camera answers it as JSON with the JPEG in base64.

    python3 src/camera_hub.py    # self-check on localhost ports 10108/10109
"""

import base64
import json
import socket
import threading
import time

MAGIC = b"OCAM"
REQUEST_PORT = 10008  # on the robot
FRAME_PORT = 10009    # on the gateway
REQUEST_EVERY = 1.0   # s between two requests to one robot


def pack_frame(header: dict, jpeg: bytes) -> bytes:
    return MAGIC + json.dumps(header, separators=(",", ":")).encode() + b"\n" + jpeg


def unpack_frame(data: bytes):
    """(header, jpeg), or None for anything that is not a camera frame."""
    if not data.startswith(MAGIC):
        return None
    head, sep, jpeg = data[len(MAGIC):].partition(b"\n")
    if not sep:
        return None
    try:
        header = json.loads(head)
    except ValueError:
        return None
    return (header, jpeg) if isinstance(header, dict) else None


class CameraHub:
    def __init__(self, host: str = "0.0.0.0", port: int = FRAME_PORT, request_port: int = REQUEST_PORT) -> None:
        self._addr = (host, port)
        self.port = port
        self.request_port = request_port
        self._frames = {}     # (ip, id) -> (time, header, jpeg)
        self._requested = {}  # (ip, id) -> time of the last request
        self._lock = threading.Lock()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="CameraHub")

    def start(self) -> None:
        self._sock.bind(self._addr)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close()

    def request(self, ip: str, robot_id: int) -> None:
        key = (ip, robot_id)
        now = time.time()
        with self._lock:
            if now - self._requested.get(key, 0.0) < REQUEST_EVERY:
                return
            self._requested[key] = now
        msg = json.dumps({"camera": True, "id": robot_id, "port": self.port}).encode()
        try:
            self._sock.sendto(msg, (ip, self.request_port))
        except OSError as exc:  # unreachable robot: the page shows "waiting"
            print(f"[CameraHub] request to {ip}: {exc}")

    def latest(self, ip: str, robot_id: int):
        """{"age", "meta", "jpeg" (base64)} of the newest frame of this robot, or None."""
        with self._lock:
            f = self._frames.get((ip, robot_id))
        if f is None:
            return None
        t, header, jpeg = f
        return {"age": round(time.time() - t, 2), "meta": header, "jpeg": base64.b64encode(jpeg).decode()}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            frame = unpack_frame(data)
            if frame is None:
                continue
            header, jpeg = frame
            with self._lock:
                self._frames[(addr[0], int(header.get("id", 0)))] = (time.time(), header, jpeg)


if __name__ == "__main__":
    hub = CameraHub("127.0.0.1", port=10109, request_port=10108)
    robot = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    robot.bind(("127.0.0.1", 10108))
    robot.settimeout(2.0)
    hub.start()
    assert hub.latest("127.0.0.1", 3) is None
    hub.request("127.0.0.1", 3)
    hub.request("127.0.0.1", 3)  # rate-limited: no second datagram
    req, gateway = robot.recvfrom(1000)
    assert json.loads(req) == {"camera": True, "id": 3, "port": 10109}
    robot.settimeout(0.3)
    try:
        robot.recvfrom(1000)
        raise AssertionError("second request within 1 s")
    except socket.timeout:
        pass
    robot.sendto(b"not a frame", gateway)
    robot.sendto(pack_frame({"id": 3, "w": 2, "h": 1}, b"\xff\xd8JPEG\n\xff\xd9"), gateway)
    for _ in range(50):
        got = hub.latest("127.0.0.1", 3)
        if got:
            break
        time.sleep(0.02)
    assert got and got["meta"] == {"id": 3, "w": 2, "h": 1}, got
    assert base64.b64decode(got["jpeg"]) == b"\xff\xd8JPEG\n\xff\xd9"  # a newline in the JPEG survives
    assert unpack_frame(b"OCAM{bad\n") is None and unpack_frame(b"OCAM{}") is None
    hub.stop()
    robot.close()
    print("camera_hub self-check OK")
