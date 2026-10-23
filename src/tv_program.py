"""TV program of the public TV view (src/tv.html) and the director console (src/director.html).

The gateway keeps one program in memory. POST /tv changes it, /state carries it as "tv", GET /tv returns it with the
team names. The TV page runs the AUTO shots itself (src/static/tv_auto.js); this file only stores what the director set.
POST /tv cannot move a robot, so it needs no control lock.

    python3 src/tv_program.py    # self-check
"""

import re
import threading
import time

ROBOT_KEY = re.compile(r"^\d{1,3}(\.\d{1,3}){3}\|\d{1,3}$")  # "<ip>|<id>", as /camera?robot=
VIEW_ROBOTS = {"field": (0, 2), "camera": (1, 1), "split": (1, 2)}  # view -> (min, max) robots


class TVProgram:
    # ponytail: one program for every TV, lost on a gateway restart; add ?screen= or a file when a match needs it.
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.tv = {"rev": 0, "mode": "auto", "view": "field", "robots": [], "engine": "2d",
                   "banner": "", "banner_until": 0.0, "by": "", "t": clock()}

    def view(self) -> dict:
        """The program as clients see it: seconds left for the banner and the age, from the gateway's clock."""
        now = self._clock()
        with self._lock:
            tv = dict(self.tv)
        return {"rev": tv["rev"], "mode": tv["mode"], "view": tv["view"], "robots": list(tv["robots"]),
                "engine": tv["engine"], "banner": tv["banner"], "banner_left": round(max(0.0, tv["banner_until"] - now), 1),
                "by": tv["by"], "age": round(now - tv["t"], 1)}

    def update(self, body, live: set) -> tuple:
        """Apply a POST /tv body; live = {"<ip>|<id>"} of the robots that send data now.
        Returns (HTTP code, answer). Nothing changes unless the whole body is valid."""
        if not isinstance(body, dict):
            return 400, {"error": "Send a JSON object."}
        if any(k in body and not isinstance(body[k], str) for k in ("mode", "view", "engine", "banner", "by")):
            return 400, {"error": "mode, view, engine, banner and by must be text."}
        now = self._clock()
        with self._lock:
            new = dict(self.tv)
            if "mode" in body:
                if body["mode"] not in ("auto", "manual"):
                    return 400, {"error": "mode must be auto or manual."}
                new["mode"] = body["mode"]
            if "view" in body:
                if body["view"] not in VIEW_ROBOTS:
                    return 400, {"error": "view must be field, camera or split."}
                new["view"] = body["view"]
                if "mode" not in body:
                    new["mode"] = "manual"
            if "robots" in body:
                robots = body["robots"]
                if not isinstance(robots, list) or len(robots) > 2 or not all(isinstance(r, str) and ROBOT_KEY.match(r) for r in robots):
                    return 400, {"error": "robots must be a list of at most 2 robots as <ip>|<id>."}
                new["robots"] = list(robots)
            if "robots" in body or "view" in body:
                lo, hi = VIEW_ROBOTS[new["view"]]
                if not lo <= len(new["robots"]) <= hi:
                    return 400, {"error": f"The {new['view']} view needs {lo if lo == hi else f'{lo} or {hi}'} robots."
                                 if new["view"] != "field" else "The field view takes at most 2 robots."}
                if any(r not in live for r in body.get("robots", [])):
                    return 409, {"error": "That robot sends no data now."}
            if "engine" in body:
                if body["engine"] not in ("2d", "3d"):
                    return 400, {"error": "engine must be 2d or 3d."}
                new["engine"] = body["engine"]
            if "banner_s" in body:
                s = body["banner_s"]
                if isinstance(s, bool) or not isinstance(s, int) or not 3 <= s <= 120:
                    return 400, {"error": "banner_s must be a whole number from 3 to 120."}
            if "banner" in body:
                new["banner"] = body["banner"].strip()[:80]
                new["banner_until"] = now + body.get("banner_s", 10) if new["banner"] else 0.0
            if "by" in body:
                new["by"] = body["by"][:40]
            new["rev"] += 1
            new["t"] = now
            self.tv = new
        return 200, self.view()


if __name__ == "__main__":
    t = [1000.0]
    p = TVProgram(clock=lambda: t[0])
    live = {"127.0.0.1|3", "127.0.0.1|4"}
    v = p.view()
    assert (v["rev"], v["mode"], v["view"], v["engine"], v["banner_left"]) == (0, "auto", "field", "2d", 0), v
    # errors change nothing (G2)
    for body, code in [({"view": "tv"}, 400), ({"view": "camera", "robots": ["127.0.0.1|99"]}, 409),
                       ({"view": "split", "robots": []}, 400), ({"robots": ["../x|1"]}, 400), ([1], 400),
                       ({"mode": "x"}, 400), ({"engine": "4d"}, 400), ({"banner": "x", "banner_s": True}, 400),
                       ({"banner": "x", "banner_s": 2}, 400), ({"view": "camera"}, 400),
                       ({"robots": ["127.0.0.1|3", "127.0.0.1|4", "127.0.0.1|3"]}, 400),
                       ({"engine": "3d", "view": "split", "robots": []}, 400), ({"view": []}, 400), ({"view": {}}, 400),
                       ({"banner": None}, 400), ({"by": 3}, 400)]:
        got = p.update(body, live)[0]
        assert got == code, (body, got)
    assert p.view()["rev"] == 0 and p.view()["engine"] == "2d"
    # view without mode -> manual, rev + 1 (G3)
    code, v = p.update({"view": "camera", "robots": ["127.0.0.1|3"], "by": "Ann"}, live)
    assert code == 200 and (v["mode"], v["view"], v["robots"], v["rev"], v["by"]) == ("manual", "camera", ["127.0.0.1|3"], 1, "Ann"), v
    # two robots while the view is camera: refused against the resulting view
    assert p.update({"robots": ["127.0.0.1|3", "127.0.0.1|4"]}, live)[0] == 400
    assert p.update({"view": "split", "robots": ["127.0.0.1|3", "127.0.0.1|4"]}, live)[0] == 200
    # a robot that went offline stays in the program; only a body that names it again is checked
    assert p.update({"mode": "auto"}, set())[0] == 200 and p.view()["view"] == "split"
    # banner: 80 characters, counts down, 0 after banner_s (G4); "" clears it
    code, v = p.update({"banner": "  " + "x" * 200, "banner_s": 5}, live)
    assert code == 200 and len(v["banner"]) == 80 and v["banner_left"] == 5, v
    t[0] += 2
    assert p.view()["banner_left"] == 3 and p.view()["age"] == 2
    t[0] += 4
    assert p.view()["banner_left"] == 0
    assert p.update({"banner": "hi"}, live)[1]["banner_left"] == 10  # default 10 s
    assert p.update({"banner": ""}, live)[1]["banner_left"] == 0
    print("tv_program: all checks passed")
