"""oraculum launcher: a signed-in SPQRTeam member starts their own hosted simulation session (one Modal sandbox).

    browser → nginx (oraculum.emanuelemusumeci.com) → auth_request → oauth2-proxy (GitHub, org SPQRTeam)
            → this server on 127.0.0.1:18100 → Modal (sandbox from the image built by hosted/modal_session.py)

It is the middleman: it holds the Modal token (users never see it) and logs usage per GitHub user in usage.jsonl.
It trusts only the X-Auth-Request-User header, which nginx sets from the oauth2-proxy answer.

Limits (decided by the user on 2026-10-19): 2 sessions at once, 30 min each, 10 min with no open page, $3 per UTC day.
One running session per user is this file's own default.

Env: ORACULUM_IMAGE_ID (im-..., printed by `hosted/modal_session.py start`), MODAL_TOKEN_ID / MODAL_TOKEN_SECRET,
LAUNCHER_DATA (default /data: sessions.json and usage.jsonl).

    python3 launcher.py               # serve on 127.0.0.1:18100
    python3 launcher.py --selftest    # limit and cost checks, no Modal, no network
"""

import json
import os
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_NAME = "oraculum-hosted"
MINUTES, IDLE_MINUTES, MAX_PARALLEL, PER_USER, DAILY_CAP_USD = 30, 10, 2, 1, 3.0
CPU, MEMORY = (4.0, 5.0), (4096, 6144)  # (request, limit); measured use ~4.5 cores, 1.3-2 GB
# Modal Sandbox rates ($0.1419/core-h, $0.024/GiB-h) at the limits; billed max(request, usage), checked on the bill.
USD_PER_HOUR = CPU[1] * 0.1419 + MEMORY[1] / 1024 * 0.024
DATA = Path(os.environ.get("LAUNCHER_DATA", "/data"))


# ---- limits and cost (pure, see --selftest) ----

def day_start(now: float) -> float:
    return now - now % 86400  # 00:00 UTC


def budget(sessions: dict, unknown_running: int, now: float) -> tuple:
    """(spent today, reserved for running sessions) in USD. A running session reserves the rest of its 30 minutes;
    a running sandbox the launcher did not start (the laptop CLI) reserves a full session."""
    spent = reserved = 0.0
    for s in sessions.values():
        end = s["end"] or now
        if end > day_start(now):
            spent += (end - max(s["start"], day_start(now))) / 3600 * USD_PER_HOUR
        if s["end"] is None:
            reserved += max(0.0, s["start"] + MINUTES * 60 - now) / 3600 * USD_PER_HOUR
    return spent, reserved + unknown_running * MINUTES / 60 * USD_PER_HOUR


def refusal(user: str, sessions: dict, running_ids: set, now: float) -> str:
    """Why `user` may not start a session now, or "" if they may."""
    if sum(1 for s in sessions.values() if s["user"] == user and s["end"] is None) >= PER_USER:
        return "You already have a running session. Stop it first."
    if len(running_ids) >= MAX_PARALLEL:
        return f"{len(running_ids)} sessions are running, the maximum is {MAX_PARALLEL}. Try again when one ends."
    spent, reserved = budget(sessions, len(running_ids - set(sessions)), now)
    if spent + reserved + MINUTES / 60 * USD_PER_HOUR > DAILY_CAP_USD:
        return f"Today's budget is used: ${spent + reserved:.2f} of ${DAILY_CAP_USD:.2f}. It resets at 00:00 UTC."
    return ""


# ---- state: sessions.json (Modal decides what is running), usage.jsonl (one line per event) ----

class Store:
    def __init__(self, modal_module=None):
        self.modal = modal_module
        self.lock = threading.Lock()  # ponytail: one lock for everything; a start holds it ~30 s, fine for 2 sessions
        self.path = DATA / "sessions.json"
        self.sessions = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.running, self._checked = set(), 0.0
        self.app = self.modal.App.lookup(APP_NAME, create_if_missing=True) if self.modal else None

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.sessions, indent=1))
        tmp.chmod(0o600)  # holds the session tokens
        tmp.replace(self.path)

    def log(self, event: str, **fields):
        with open(DATA / "usage.jsonl", "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}) + "\n")

    def refresh(self, force=False):
        """Ask Modal which sandboxes of the app run (at most every 5 s); close the sessions that ended."""
        if not force and time.time() - self._checked < 5:
            return
        self.running = {sb.object_id for sb in self.modal.Sandbox.list(app_id=self.app.app_id)}
        self._checked = now = time.time()
        for sid, s in self.sessions.items():
            if s["end"] is None and sid not in self.running:
                s["end"] = now
                minutes = (now - s["start"]) / 60
                self.log("end", user=s["user"], session=sid, minutes=round(minutes, 1),
                         est_usd=round(minutes / 60 * USD_PER_HOUR, 3))
        self._save()

    def start(self, user: str) -> dict:
        m = self.modal
        self.refresh(force=True)
        why = refusal(user, self.sessions, self.running, time.time())
        if why:
            self.log("refused", user=user, reason=why)
            raise PermissionError(why)
        token = secrets.token_urlsafe(16)
        sb = m.Sandbox.create("bash", "/opt/session/session.sh", app=self.app, image=m.Image.from_id(os.environ["ORACULUM_IMAGE_ID"]),
                              cpu=CPU, memory=MEMORY, timeout=MINUTES * 60, idle_timeout=IDLE_MINUTES * 60,
                              encrypted_ports=[8080, 6080], cidr_allowlist=["127.0.0.1/32"],  # no outbound network
                              secrets=[m.Secret.from_dict({"ORACULUM_ACCESS_TOKEN": token})])
        sb.set_tags({"user": user, "by": "launcher"})
        tunnels = sb.tunnels()
        self.sessions[sb.object_id] = {"user": user, "start": time.time(), "end": None, "token": token,
                                       "gateway": tunnels[8080].url, "vnc": tunnels[6080].url}
        self.running.add(sb.object_id)
        self._save()
        self.log("start", user=user, session=sb.object_id)
        return self.sessions[sb.object_id]

    def stop(self, user: str, sid: str):
        s = self.sessions.get(sid)
        if not s or s["user"] != user:
            raise PermissionError("Not your session.")
        self.modal.Sandbox.from_id(sid).terminate()
        self.refresh(force=True)

    def view(self, user: str) -> dict:
        self.refresh()
        now = time.time()
        spent, reserved = budget(self.sessions, len(self.running - set(self.sessions)), now)
        mine = []
        for sid, s in sorted(self.sessions.items(), key=lambda kv: -kv[1]["start"]):
            if s["user"] != user or (s["end"] and now - s["end"] > 7 * 86400):
                continue
            row = {"id": sid, "start": s["start"], "end": s["end"], "minutes": round(((s["end"] or now) - s["start"]) / 60, 1)}
            if s["end"] is None:
                t = s["token"]
                row.update(oraculum=f"{s['gateway']}/index.html?token={t}", fleet=f"{s['gateway']}/fleet.html?token={t}",
                           circus=f"{s['vnc']}/vnc.html?autoconnect=1&resize=scale&password={t}",
                           ends_by=s["start"] + MINUTES * 60)
            mine.append(row)
        return {"user": user, "sessions": mine[:10], "running": len(self.running), "max_parallel": MAX_PARALLEL,
                "spent_usd": round(spent, 2), "reserved_usd": round(reserved, 2), "cap_usd": DAILY_CAP_USD,
                "minutes": MINUTES, "idle_minutes": IDLE_MINUTES, "refusal": refusal(user, self.sessions, self.running, now)}


# ---- HTTP ----

def serve(store: Store, port: int = 18100):
    page = (Path(__file__).parent / "launcher.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _user(self):
            user = self.headers.get("X-Auth-Request-User", "")  # set by nginx from oauth2-proxy, never by the browser
            if not user:
                self._send(401, b'{"error": "not signed in"}')
            return user

        def do_GET(self):
            user = self._user()
            if not user:
                return
            if self.path == "/" or self.path.startswith("/?"):
                self._send(200, page, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                with store.lock:
                    self._send(200, json.dumps(store.view(user)).encode())
            else:
                self._send(404, b'{"error": "not found"}')

        def do_POST(self):
            user = self._user()
            if not user:
                return
            if self.headers.get("Content-Type", "") != "application/json":  # a cross-site form cannot set this
                return self._send(415, b'{"error": "expected application/json"}')
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                with store.lock:
                    if self.path == "/api/start":
                        store.start(user)
                    elif self.path == "/api/stop":
                        store.stop(user, str(body.get("id", "")))
                    else:
                        return self._send(404, b'{"error": "not found"}')
                    self._send(200, json.dumps(store.view(user)).encode())
            except PermissionError as e:
                self._send(403, json.dumps({"error": str(e)}).encode())
            except Exception as e:  # Modal errors: show them, keep serving
                store.log("error", user=user, path=self.path, error=str(e)[:300])
                self._send(502, json.dumps({"error": f"Modal: {str(e)[:200]}"}).encode())

    print(f"oraculum launcher on 127.0.0.1:{port}, image {os.environ.get('ORACULUM_IMAGE_ID')}, "
          f"cap ${DAILY_CAP_USD}/day at ${USD_PER_HOUR:.3f}/session-hour", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def selftest():
    now = 20_370 * 86400 + 12 * 3600.0  # 12:00 UTC on 2025-10-09
    s = lambda user, start_min_ago, end_min_ago=None: {  # noqa: E731
        "user": user, "start": now - start_min_ago * 60, "end": None if end_min_ago is None else now - end_min_ago * 60}
    assert refusal("ann", {}, set(), now) == ""
    one = {"sb-1": s("ann", 10)}
    assert "already" in refusal("ann", one, {"sb-1"}, now)
    assert refusal("bob", one, {"sb-1"}, now) == ""
    two = {"sb-1": s("ann", 10), "sb-2": s("bob", 5)}
    assert "maximum" in refusal("cid", two, {"sb-1", "sb-2"}, now)
    assert "maximum" in refusal("cid", one, {"sb-1", "sb-cli"}, now)  # a CLI sandbox counts too
    # budget: a finished 60-min session costs one hour; a running one reserves the rest of its 30 minutes
    spent, reserved = budget({"a": s("ann", 120, 60)}, 0, now)
    assert abs(spent - USD_PER_HOUR) < 1e-9 and reserved == 0
    spent, reserved = budget({"a": s("ann", 10)}, 1, now)
    assert abs(spent - USD_PER_HOUR / 6) < 1e-9 and abs(reserved - USD_PER_HOUR * (20 + 30) / 60) < 1e-9
    # yesterday does not count; a session across midnight counts from 00:00
    assert budget({"a": s("ann", 13 * 60, 12.5 * 60)}, 0, now)[0] == 0
    assert abs(budget({"a": s("ann", 12 * 60 + 30, 12 * 60 - 30)}, 0, now)[0] - USD_PER_HOUR / 2) < 1e-9
    # the cap: seven finished 30-min sessions ($2.99) leave no room for one more (~$0.43); five ($2.13) do
    assert "budget" in refusal("bob", {f"sb-{i}": s("ann", 40 * i + 30, 40 * i) for i in range(7)}, set(), now)
    assert refusal("bob", {f"sb-{i}": s("ann", 40 * i + 30, 40 * i) for i in range(5)}, set(), now) == ""
    assert 0.85 < USD_PER_HOUR < 0.86
    print(f"launcher self-check OK (${USD_PER_HOUR:.4f} per session-hour, ${MINUTES / 60 * USD_PER_HOUR:.2f} per session)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        import modal

        DATA.mkdir(parents=True, exist_ok=True)
        serve(Store(modal))
