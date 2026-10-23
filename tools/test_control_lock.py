"""Check of the Release guard in src/control_lock.py: after a release, a joystick command of the same client does not
take the free lock back; an explicit Take does. Run: python3 tools/test_control_lock.py (exit 0 = pass)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from control_lock import STALE_S, ControlLock  # noqa: E402

t = [1000.0]
lk = ControlLock(clock=lambda: t[0])
assert lk.take("a", "Ann") == "granted"
lk.release("a")
assert not lk.acquire_for_command("a", "Ann") and lk.view()["holder"] is None  # the late command is refused
assert lk.acquire_for_command("b", "Bob")  # another client still gets the free lock
lk.release("b")
assert lk.take("a", "Ann") == "granted" and lk.acquire_for_command("a", "Ann")  # Take works at once
lk.release("a")
t[0] += STALE_S + 1
assert lk.acquire_for_command("a", "Ann")  # after STALE_S the old rule holds again
lk.release("c")  # a client that held nothing (Cancel of a request) is not blocked
assert lk.acquire_for_command("a", "Ann") and not lk.acquire_for_command("c", "Cid")  # (held by a: normal refusal)
print("test_control_lock OK")
