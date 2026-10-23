"""Engineer mode: one operator at a time drives the robots, across every page and the CLI.

A client (one browser tab, one CLI run) has a random id and a display name. A manual command (POST /control with
isManual, or a resume) needs the lock: a free lock goes to the first client that asks; a held lock moves only when
its holder grants a request, releases it, or disappears (no request from it for STALE_S seconds: a closed tab).
STOP and DAMP never need the lock. /state shows names only, never client ids (an id is the right to drive).

    python3 src/control_lock.py    # self-check
"""

import threading
import time

STALE_S = 15.0


class ControlLock:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.holder = None    # {"client", "name", "seen"}
        self.request = None   # {"client", "name", "seen"}: someone asked the holder
        self._denied = set()  # clients whose last request was denied (shown once)
        self._released = {}   # client -> time it released the lock: no command takes the free lock back for STALE_S

    def _expire(self, now: float) -> None:
        if self.holder and now - self.holder["seen"] > STALE_S:
            self.holder = None
        if self.request and now - self.request["seen"] > STALE_S:
            self.request = None
        if not self.holder and self.request:  # the holder left: the waiting client gets the free lock
            self.holder, self.request = self.request, None

    def seen(self, client: str) -> None:
        """Any request from this client (a /state poll, a command) keeps its hold or its request alive."""
        if not client:
            return
        with self._lock:
            now = self._clock()
            for entry in (self.holder, self.request):
                if entry and entry["client"] == client:
                    entry["seen"] = now
            self._expire(now)

    def take(self, client: str, name: str) -> str:
        """'granted' (free, or already yours), 'asked' (the holder sees your request) or 'busy' (another request waits)."""
        if not client:
            raise ValueError("client id missing")
        name = (name or "operator")[:40]
        with self._lock:
            now = self._clock()
            self._expire(now)
            self._denied.discard(client)
            self._released.pop(client, None)  # an explicit Take always works
            if not self.holder or self.holder["client"] == client:
                self.holder = {"client": client, "name": name, "seen": now}
                if self.request and self.request["client"] == client:
                    self.request = None
                return "granted"
            if self.request and self.request["client"] != client:
                return "busy"
            self.request = {"client": client, "name": name, "seen": now}
            return "asked"

    def answer(self, client: str, grant: bool) -> bool:
        """The holder grants or denies the waiting request. False if `client` is not the holder or nobody waits."""
        with self._lock:
            self._expire(self._clock())
            if not (self.holder and self.holder["client"] == client and self.request):
                return False
            if grant:
                self.holder, self.request = dict(self.request, seen=self._clock()), None
            else:
                self._denied.add(self.request["client"])
                self.request = None
            return True

    def release(self, client: str) -> None:
        with self._lock:
            now = self._clock()
            if self.holder and self.holder["client"] == client:
                self.holder = None
                # a joystick command already on its way must not take the free lock again (the page's Release race)
                self._released = {c: t for c, t in self._released.items() if now - t < STALE_S}
                self._released[client] = now
            if self.request and self.request["client"] == client:
                self.request = None
            self._expire(self._clock())

    def acquire_for_command(self, client: str, name: str) -> bool:
        """A manual command: True if `client` holds the lock now (a free lock is taken; a held one is not asked for).
        A client that released the lock less than STALE_S ago does not get the free lock back: it must Take it."""
        if not client:
            return False
        with self._lock:
            now = self._clock()
            self._expire(now)
            if not self.holder:
                if now - self._released.get(client, -STALE_S) < STALE_S:
                    return False
                self.holder = {"client": client, "name": (name or "operator")[:40], "seen": now}
            if self.holder["client"] != client:
                return False
            self.holder["seen"] = now
            return True

    def holder_name(self) -> str:
        with self._lock:
            self._expire(self._clock())
            return self.holder["name"] if self.holder else ""

    def view(self, client: str = "") -> dict:
        with self._lock:
            self._expire(self._clock())
            mine = bool(client) and self.holder is not None and self.holder["client"] == client
            asked = bool(client) and self.request is not None and self.request["client"] == client
            denied = client in self._denied
            self._denied.discard(client)
            return {"holder": self.holder["name"] if self.holder else None, "you": mine,
                    "request": self.request["name"] if self.request and mine else None,  # only the holder sees who asks
                    "waiting": asked, "denied": denied}


if __name__ == "__main__":
    t = [1000.0]
    lk = ControlLock(clock=lambda: t[0])
    assert lk.view("a")["holder"] is None
    assert lk.take("a", "Ann") == "granted" and lk.view("a")["you"] and lk.view("b")["holder"] == "Ann"
    assert not lk.view("b")["you"] and lk.view("b")["request"] is None
    assert lk.take("b", "Bob") == "asked" and lk.view("a")["request"] == "Bob" and lk.view("b")["waiting"]
    assert lk.take("c", "Cid") == "busy"
    assert not lk.answer("b", True)                 # only the holder answers
    assert lk.answer("a", False) and lk.view("b")["denied"] and not lk.view("b")["denied"]  # denial shown once
    assert lk.view("a")["you"]
    assert lk.take("b", "Bob") == "asked" and lk.answer("a", True)
    assert lk.view("b")["you"] and not lk.view("a")["you"] and lk.holder_name() == "Bob"
    assert not lk.acquire_for_command("a", "Ann") and lk.acquire_for_command("b", "Bob")
    assert not lk.acquire_for_command("", "anon")
    # a closed tab: the holder stops polling, the waiting client gets the lock after STALE_S
    assert lk.take("c", "Cid") == "asked"
    t[0] += STALE_S - 1
    lk.seen("c")
    t[0] += 2
    lk.seen("c")
    assert lk.view("c")["you"] and lk.holder_name() == "Cid"
    lk.release("c")
    assert lk.view()["holder"] is None and lk.acquire_for_command("a", "Ann")
    print("control_lock self-check OK")
