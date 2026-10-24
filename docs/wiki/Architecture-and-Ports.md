# Architecture and Ports

Result first: one gateway process (`src/control_server.py`) receives UDP from the robots and the GameController, keeps
one merged state in memory, and serves it over HTTP on port 8080. Every client (page, phone, CLI) polls that state.
Commands go back to the robots as UDP datagrams. With the match switch (`match: true` in `config.yaml` or
`ORACULUM_MATCH=1`) the gateway sends no datagram at all: it only receives.

![Data flow](images/architecture.png)

```
GameController ──UDP 3838 (binary game state)─────────────► robots, oraculum gateway
robot (Maximus) ──UDP 10006 (JSON telemetry + drawings)───► oraculum gateway
oraculum gateway ──UDP 10007 (JSON joystick, STOP, ...)───► robot (LowControlBridge)    [not in match mode]
oraculum gateway ──UDP 10008 (camera request)─────────────► robot (DebugCameraSender)  [not in match mode]
robot ──UDP 10009 (camera frames, 3 s per request)────────► oraculum gateway
robots ◄──UDP 10000+team (binary team messages)──────────► robots, oraculum gateway (listen only)
robot ──UDP 3939 (GameController return, 32 bytes)───────► GameController; oraculum gateway when it is the robots' GC host
browser, phone, CLI ◄──HTTP 8080 (/state, /control, ...)──► oraculum gateway
```

Some older design documents describe a desktop app, a Flutter app, a React app and a WebSocket server. These do not
exist. The pages use plain HTTP polling.

## Ports

| Port | Protocol | Direction | What | Set in |
|---|---|---|---|---|
| 8080 | TCP (HTTP) | clients → gateway | Pages and API | Fixed in `src/control_server.py` |
| 10006 | UDP | robot → gateway | Telemetry and debug drawings: 10/s in practice, 1/s in match | `config.yaml` `socket.port`; robot: `DebugMessageSender` |
| 10007 | UDP | gateway → robot | Joystick, safety commands, Get up, Sit down, Go to (practice only; never with the gateway match switch) | Robot: `LowControlBridge` |
| 10008 | UDP | gateway → robot | Camera request (practice only; never to a read-only robot, never to a robot with `sys.link` "telemetry", never with the match switch) | Robot: `DebugCameraSender`; gateway: `src/camera_hub.py` |
| 10009 | UDP | robot → gateway | Camera frames, 4 per second for 3 s after each request | `config.yaml` `camera.port` (default 10009) |
| 3838 | UDP | GameController → all | Referee state (versions 19 and 20 of the packet) | `config.yaml` `game_controller.port` |
| 10000 + team | UDP | robot ↔ robot, broadcast | Team messages (SPQRMessage). The gateway listens (never sends): own team, both teams of the GameController packet, `reception.teams` | Robot: `TeamMessageSender`; gateway: `src/reception.py` |
| 3939 | UDP | robot → GameController | GameController return packets. The gateway receives them only when the robots take this host for the GameController (simulated referee, or `gameController.address` in the robot's `settings.yaml`). It binds 3939 once at start, without reuse flags; if the GameController runs on the same host, start the GameController first (or set `reception.gc_return: false`) | Robot: `GameControllerReturnMessageSender`; gateway: `src/reception.py` |

## The gateway

- `UDPReceiver` (`src/socket_client.py`) merges the packets of all robots. A robot is keyed by its IP and its player
  number, so two teams can both have a robot 3. A robot disappears 3.5 s after its last packet.
- `GCReceiver` (`src/gc_client.py`) parses the GameController packet. `own_team` in `config.yaml` selects our team.
- `Reception` (`src/reception.py`) receives robots on **any branch**, at the same time as the telemetry, and sends
  nothing (also without the match switch):
  - team messages on UDP 10000 + team. Two formats are detected per packet: `rcap` (branches `mappazzone` and
    `RCAP2026-DEV`) and `main` (the older `main`). A packet must parse to its last byte in one format, else it is only
    counted (other teams, unknown branches). Ports 10006-10009 (teams 6-9) are the gateway's own: not listened to.
  - GameController return packets on UDP 3939.
  - `GET /state` merges them per robot (sender IP, team, player) with the telemetry. Per field the newest source that
    is fresh (3.5 s) and has the highest priority wins: telemetry > team message > GameController return. Each agent
    has `sources` (`["debug", "team", "gc"]`), `source_age` and `readonly`. `/state` `reception` counts the packets per
    team (decoded, unknown format) for the message budget.
  - A robot with no telemetry is **read-only**: `readonly: true`, `sys.link: "none"`. Every command route reads only the
    telemetry receiver, so such a robot is never a target (STOP ALL included); `/control` to its address answers 409.
    The pages show a tag `DBG`, `TM`, `GC` (e.g. `TM · read-only`) and disable its buttons.
  - Frames: team messages and return packets are in the robot's own team frame. The team colour comes from the
    GameController (else from a telemetry robot of the same team); `frames.mirror_team_color` is mirrored as the
    telemetry. With no colour known: `color: ""`, `frame: "team"`, not mirrored.
  - Checks: `python3 tools/test_reception.py` (in-process; also the robot bytes in `tools/golden/`),
    `python3 tools/reception_check.py <outdir>` (browser).
- `EventLog` and `Recorder` (`src/session.py`) detect events and write recordings.
- `CameraHub` (`src/camera_hub.py`) asks a robot for camera frames (at most once per second) and keeps the newest
  frame. It asks only robots that send debug telemetry on UDP 10006. It never asks a read-only robot, a robot with
  `sys.link` "telemetry", or any robot when the match switch is on.
- `ControlLock` (`src/control_lock.py`) decides which operator may drive (see [Safety Controls](Safety-Controls)).
- `TVProgram` (`src/tv_program.py`) holds the program of the TV screens.
- `SimGameController` (`src/sim_gc.py`) is the simulated referee. It runs only with `ORACULUM_SIM_GC`, never with the
  match switch.
- `ControlServer.blocked()` (`src/control_server.py`) is the one guard of every datagram the gateway sends. With the
  match switch it returns the rule text, and nothing goes out. Check: `python3 tools/test_match.py`.

## The robot side (spqrbooster2026)

| Part | File | Does |
|---|---|---|
| Settings | `src/app/utils/settings/Settings.h`, `Settings.cpp` | Reads `oraculum` and `oraculumHost` from `deploy.yaml`. Telemetry runs when `oraculum` is not `off` or `useRerun` is true. Remote control runs in `practice`, or in `off` with `useRerun`. |
| Telemetry | `src/app/nodes/communication_send/DebugMessageSender.cpp` | One JSON datagram per period (100 ms; 1000 ms in match) to the target. Target: `oraculumHost`; else env `ORACULUM_HOST`; else the host of `rerun.connectAddr` in `connect` mode; else the Wi-Fi broadcast. In match: `oraculumHost` only. |
| Camera | `src/app/nodes/communication_send/DebugCameraSender.cpp` | After a request on UDP 10008: 3 s of frames, 4 per second, a JPEG at most 320 px wide, the camera model and the detections. Practice only. |
| Commands | `src/app/nodes/bridge/LowControlBridge.h`, `.cpp` | Reads JSON datagrams on UDP 10007 with `"isManual": true`. While they arrive, they replace the remote controller; 500 ms after the last one, the remote controller is back. Sets the STOP, LIE, DAMP, GET UP and GO TO latches (SIT is logged and ignored: the SDK has no sit call). Practice only. |
| Go to | `Root` state `go_to_pose` | Walks to the target with the robot's own localization, then stands. Telemetry `goto` `{x, y, theta}` while the latch is `goto`. |
| Deploy | `scripts/deploy.sh` | `--no-rerun` (used by `deploy-match`) sets `useRerun: false` and turns `practice` into `match`. |

## HTTP routes

All routes need the access token when `ORACULUM_ACCESS_TOKEN` is set (`?token=` once, then the cookie).

| Route | Does |
|---|---|
| `GET /state` | The merged state: `agents`, `ball`, `drawings`, `texts`, `gamecontroller`, `fleet`, `rec`, `lock`, `bypass`, `last_event`, `tv`, `boot`, `restart`, `match`. Add `?client=<id>` to keep your control lock alive. `match` = true: the gateway runs with its match switch. |
| `GET /field` | The field dimensions from `config.yaml` (`fields/*.yaml`, metres). |
| `GET /events?since=<id>` | Events newer than `id`. |
| `POST /events` | `{"add": {"text": "...", "robot": "T19 R3"}}` adds a mark; `{"delete": <id>}` deletes an event. |
| `POST /record` | `{"on": true, "by": "<name>"}` starts; `{"on": false, "name": "<recording name>"}` stops that recording. |
| `GET /recordings` | The list of recordings. `GET /recordings/<name>.jsonl` downloads one. |
| `GET /camera?robot=<ip>\|<id>` | The newest camera frame (JSON, JPEG in base64), or `{"status": "waiting"}`. Each call also asks the robot (UDP 10008, at most once per second) to send 3 s of frames to UDP 10009. The gateway does not ask a read-only robot (no debug telemetry), a robot with `sys.link` "telemetry", or any robot when the match switch is on. For these robots the robot page tells why it has no camera image. |
| `POST /control` | A manual command `{ip, vx, vy, vtheta, isManual: true, client, operator, ...}`. Needs the control lock (else 423). Refused in READY, SET and PLAYING (403) unless `testingOverride` is true. 409 in match mode. |
| `POST /stop` | `{robot: "<ip>" or "all", kind: "stop" \| "lie" \| "damp" \| "resume" \| "getup" \| "sit", client, name, confirm, testingOverride}`. `getup` and `sit` need the control lock (423) and get 403 in READY, SET and PLAYING without `testingOverride`. `sit` only for a robot that reports `robot` "t2" (else 409); "all" = every T2. 409 for match-mode and damped robots, and for every kind in match mode. |
| `GET /positions` | `{frame: "team", positions: [{id, label, x, y, theta, player}]}` from `config/positions.yaml` (READY positions `ready_N`, side line `sideline_N`, `sideline_penalized`; values of the framework's `formationRCAP.yaml`). `?robot=<ip>`: the same list in the shared field frame of that robot's team (`frame: "field"`); 409 for an unknown IP. |
| `POST /goto` | `{robot: "<ip>", x, y, theta}` (field frame, m, rad) or `{robot, pos: "<id of /positions>"}`: one robot walks there, then stands. `{robot, cancel: true}` stops the walk. Rules as `getup`; 400 for a bad body or a target more than 1 m off the field; 409 in match mode. |
| `POST /control_lock` | `{action: "take" \| "release" \| "grant" \| "deny", client, name}`. |
| `GET /tv`, `POST /tv` | Read or change the TV program. |
| `POST /gc` | Only with the simulated referee: `{state, kicking_team, goal, half, penalty}`. Else 404; 409 in match mode. |
| `GET /static/<path>` | Files from `src/static/`. |
| `GET /`, `/dashboard`, `/fleet`, `/robot`, `/tv.html`, `/director` | The pages. |

## Message format

The telemetry schema is the set of dataclasses in the SCHEMA section of `src/socket_client.py` (`AgentMsg`, `BallMsg`,
`DrawingMsg`, `TextMsg`, `GameStateMsg`). New fields need a default value. The gateway ignores unknown fields.

- Units are metres and radians. The frame is the field frame. Robots of the colour in `frames.mirror_team_color`
  (default `blue`) send in their own team frame; the gateway mirrors them.
- Drawing coordinates: `circle [x, y]` with `size` = radius, `box [cx, cy, w, h]`, `line [x1, y1, x2, y2]`,
  `arc [x, y, r, start_deg, end_deg]`, `point [x, y]`. `tools/udp_sender.py` sends one of each.
- `joints` maps T1 joint names (for example `AAHead_yaw`) to radians. The MuJoCo 3D engine uses them.
- `sys` carries the fleet data: version, CPU, load, temperature, Wi-Fi traffic, robot log state.
- `latch` is the robot's answer to STOP, LIE DOWN and DAMP.

## Configuration

| File | Holds |
|---|---|
| `config.yaml` | Field file (`fieldRCAP.yaml`, 22 × 14 m), ports, `own_team`, team colour to mirror, drawing paths to hide, `match` (the match switch, default `false`), `reception` (switches `debug`, `team_messages`, `gc_return`, all on by default; extra `teams`). |
| `config/positions.yaml` | The positions of `GET /positions` and `POST /goto {pos}`, in the team frame (own goal at -x). |
| `config/teams.yaml` | Team numbers → names and colours (the TV shows "SPQR" for 19). |
| `fields/*.yaml` | Field dimensions. |

| Environment variable | Effect |
|---|---|
| `ORACULUM_ACCESS_TOKEN` | Every route needs this token. |
| `ORACULUM_MATCH=1` (or `0`) | Turns the match switch on (or off). It overrides `match` in `config.yaml`. With the switch on, the next three variables are ignored. |
| `ORACULUM_SIM_GC="<team A>,<team B>"` | Runs the simulated referee. The gateway then ignores UDP 3838. |
| `ORACULUM_GC_TARGETS="<ip>,<ip>"` | The simulated referee sends to these IPs (default `127.0.0.1`). |
| `ORACULUM_CONTROL_IP` | Every command goes to this address, whatever the request says. Hosted sessions only. |
