"""Ghost-only scenario export and a network-isolated Docker simulator lifecycle."""
import json
import math
import re
import time
import yaml


def normalize(value):
    if not isinstance(value, dict):
        raise ValueError("Scenario is required")
    field = value.get("field", {})
    width, height = field.get("width"), field.get("height")
    def finite(n, low, high):
        return type(n) in (int, float) and math.isfinite(n) and low <= n <= high
    if not finite(width, 6, 30) or not finite(height, 4, 20) or width <= height:
        raise ValueError("Invalid field dimensions")
    ball = value.get("ball", {})
    if ball.get("x") != 0 or ball.get("y") != 0:
        raise ValueError("The current Circus launcher starts the ball at centre; set ball X/Y to zero")
    teams = value.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise ValueError("Choose two teams")
    numbers, count = set(), 0
    for team in teams:
        number = team.get("number")
        if type(number) is not int or not 1 <= number <= 99 or number in numbers:
            raise ValueError("Team numbers must be distinct integers from 1 to 99")
        numbers.add(number)
        players = team.get("players")
        if not isinstance(players, list) or len(players) > 10:
            raise ValueError("At most ten players per team")
        seen = set()
        for player in players:
            n = player.get("number")
            if type(n) is not int or not 1 <= n <= 20 or n in seen:
                raise ValueError("Player numbers must be unique within each team")
            seen.add(n)
            if player.get("source") not in ("ghost", "real") or player.get("model") not in ("t1", "t2", "k1"):
                raise ValueError("Invalid player source/model")
            if player.get("role") not in ("goalie", "striker", "defender", "support"):
                raise ValueError("Invalid player role")
            if not finite(player.get("x"), -width/2, width/2) or not finite(player.get("y"), -height/2, height/2) or not finite(player.get("angle"), -2*math.pi, 2*math.pi):
                raise ValueError("Invalid player pose")
            count += player["source"] == "ghost"
    if not count:
        raise ValueError("Scenario contains no simulated players")
    return json.loads(json.dumps(value))


def run_session(manager, identifier, scenario):
    scenario = normalize(scenario)
    config = manager.config["simulator"]
    image = config.get("image", "")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]+", image):
        raise ValueError("Configure a pinned simulator image")
    if "@sha256:" not in image:
        raise ValueError("Simulator image must be pinned by sha256 digest")
    directory = (manager.root / (identifier + "-scenario")).resolve()
    directory.mkdir(mode=0o700, parents=True)
    teams = {}
    for color, team in zip(("red", "blue"), scenario["teams"]):
        players = []
        for p in team["players"]:
            if p["source"] != "ghost": continue
            player = {"type": "Booster-" + p["model"].upper(), "number": p["number"],
                      "position": [p["x"], p["y"], {"t1": .68, "t2": .98, "k1": .53}[p["model"]]],
                      "orientation": [0, 0, p["angle"]]}
            if p["role"] != "support": player["role"] = "goalkeeper" if p["role"] == "goalie" else p["role"]
            players.append(player)
        if players: teams[color] = {"number": team["number"], "players": players}
    (directory / "scene.yaml").write_text(yaml.safe_dump({"simulation_config": "oraculum_custom", "teams": teams}))
    w, h = scenario["field"]["width"], scenario["field"]["height"]
    x, y, scale = w/14, h/9, min(w/14, h/9)
    field = {"width":w, "height":h, "center_radius":1.5*scale, "goal_area_width":x, "goal_area_height":4*y,
             "penalty_area_width":3*x, "penalty_area_height":6.5*y, "penalty_mark_distance":2.1*x,
             "goal_width":2.6*y, "goal_height":1.8, "goal_depth":.6, "line_width":.08, "ball_radius":.11}
    (directory / "field.yaml").write_text(yaml.safe_dump(field))
    (directory / "simulation.yaml").write_text(yaml.safe_dump({"simulation":{"max_simulation_time":-1},
        "game":{"field":"oraculum_custom", "game_state_logging":True, "game_duration":600, "automatic_restart":True}}))
    name = "oraculum-sim-" + identifier
    manager._phase(identifier, "starting simulator")
    try:
        manager.runner(identifier, ["docker", "run", "-d", "--name", name, "--network", "none", "--cap-drop", "ALL",
                                   "--security-opt", "no-new-privileges", "--pids-limit", "256", "--memory", "4g", "--cpus", "2",
                                   "--mount", f"type=bind,src={directory},dst=/scenario,readonly", image,
                                   "/scenario/scene.yaml", "/scenario/field.yaml", "/scenario/simulation.yaml"], timeout=90)
        started = time.monotonic()
        while not manager.cancelled[identifier].wait(.5):
            raw = manager.runner(identifier, ["docker", "inspect", "--format", "{{json .State}}", name], timeout=10)
            status = json.loads(raw)
            if not status["Running"]:
                if status["ExitCode"]:
                    raise ValueError("Simulator exited " + str(status["ExitCode"]) + ": " + status.get("Error", ""))
                return {"message":"Simulator completed", "container":name}
            manager._phase(identifier, "simulator running")
            if time.monotonic() - started >= min(3600, max(30, config.get("max_seconds", 1800))):
                return {"message":"Session duration reached; simulator stopped", "container":name}
        return {"message":"Simulator stopped", "container":name}
    finally:
        manager.runner(identifier, ["docker", "rm", "-f", name], timeout=20, cancellable=False)
