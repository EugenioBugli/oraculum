import struct
import threading
import time
import os

class PhysicalJoystick:
    """Reads Linux joystick input from /dev/input/js0 in a background thread."""

    def __init__(self, device_path: str = "/dev/input/js0") -> None:
        self.device_path = device_path
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()

        # Current joystick state
        self.state = {
            "lx": 0.0,
            "ly": 0.0,
            "rx": 0.0,
            "ry": 0.0,
            "a": False,
            "b": False,
            "x": False,
            "y": False,
            "lb": False,
            "rb": False,
            "lt": False,
            "rt": False,
            "back": False,
            "start": False,
            "ls": False,
            "rs": False,
        }
        self.connected = False

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="PhysicalJoystick")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)

    def get_state(self) -> dict:
        with self._lock:
            return dict(self.state)

    def _run(self) -> None:
        event_format = "IhBB"
        event_size = struct.calcsize(event_format)

        while not self._stop_event.is_set():
            if not os.path.exists(self.device_path):
                self.connected = False
                time.sleep(2.0)
                continue

            try:
                with open(self.device_path, "rb") as f:
                    print(f"[Joystick] Connected to {self.device_path}")
                    self.connected = True

                    while not self._stop_event.is_set():
                        # Read one event
                        data = f.read(event_size)
                        if not data or len(data) < event_size:
                            break

                        time_ms, val, type_code, num = struct.unpack(event_format, data)
                        
                        # Strip JS_EVENT_INIT flag
                        type_code &= ~0x80

                        with self._lock:
                            if type_code == 0x01:  # Button event
                                # Map buttons
                                # 0: A, 1: B, 2: X, 3: Y, 4: LB, 5: RB, 6: Back, 7: Start, 8: Guide, 9: LS, 10: RS
                                val_bool = bool(val)
                                if num == 0: self.state["a"] = val_bool
                                elif num == 1: self.state["b"] = val_bool
                                elif num == 2: self.state["x"] = val_bool
                                elif num == 3: self.state["y"] = val_bool
                                elif num == 4: self.state["lb"] = val_bool
                                elif num == 5: self.state["rb"] = val_bool
                                elif num == 6: self.state["back"] = val_bool
                                elif num == 7: self.state["start"] = val_bool
                                elif num == 9: self.state["ls"] = val_bool
                                elif num == 10: self.state["rs"] = val_bool

                            elif type_code == 0x02:  # Axis event
                                # Map axes (-32767 to 32767 mapped to -1.0 to 1.0)
                                val_normalized = val / 32767.0
                                
                                # Clamp small noise around center
                                if abs(val_normalized) < 0.05:
                                    val_normalized = 0.0

                                # Axes map: 0: lx, 1: ly (inverted), 2: lt, 3: rx, 4: ry (inverted), 5: rt
                                if num == 0: self.state["lx"] = val_normalized
                                elif num == 1: self.state["ly"] = -val_normalized
                                elif num == 2:
                                    # LT (value ranges from -1.0 fully released to 1.0 fully pressed)
                                    # Map to True if pressed beyond halfway (value > 0)
                                    self.state["lt"] = (val_normalized > 0.0)
                                elif num == 3: self.state["rx"] = val_normalized
                                elif num == 4: self.state["ry"] = -val_normalized
                                elif num == 5:
                                    # RT
                                    self.state["rt"] = (val_normalized > 0.0)

            except Exception as e:
                print(f"[Joystick] Disconnected: {e}")
                self.connected = False
                time.sleep(2.0)
