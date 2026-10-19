# Oraculum: system description

Oraculum is team SPQR's control room for a fleet of humanoid robots (Booster T1 and K1) in RoboCup humanoid soccer.
One gateway collects the telemetry of every robot and the referee's GameController state. Any client (a browser on a
laptop, tablet or phone, or a command-line tool) reads one shared state from it. The same clients can drive or
stop robots, under one control lock. The same software also runs as a hosted simulation session: a
browser opens a private copy of the team's robot code in the circus simulator, with no installation.

Status: 2026-10-19. Screenshots: `docs/img/` (added after the GUI verification).

## 1. Architecture

```
GameController ──UDP 3838 (binary RoboCupGameControlData v19/v20)──► gateway (and the robots)
robot (Maximus) ──UDP 10006: JSON telemetry, 10 Hz (pose, role, state, battery, fall, beliefs, joints, fleet data,
                  STOP/LIE/DAMP latch, debug drawings)──► gateway
gateway ──UDP 10007: JSON joystick datagram (manual drive, STOP, LIE DOWN, DAMP, Resume)──► robot LowControlBridge
gateway ──UDP 10008: camera request──► robot DebugCameraSender ──UDP 10009: JPEG + camera model──► gateway
gateway ──HTTP 8080: /state, /control, /stop, /control_lock, /events, /record, /recordings, /camera, /gc, pages──►
          browsers, phones, CLI
```

| Part | Where | What it does |
|---|---|---|
| Gateway | `src/control_server.py` (Python standard library + PyYAML) | Merges the UDP telemetry of all robots and the GameController packets into one state; serves it over HTTP with one thread per request; sends joystick datagrams; keeps the event log, the recordings, the camera hub and the control lock. |
| Telemetry receiver | `src/socket_client.py` | Merges packets per (sender IP, robot id); drops a sender 2 s after its last packet; link rate and age per IP over a 2 s window. |
| GameController receiver | `src/gc_client.py` | Parses versions 19 and 20; a packet older than 2 s counts as no GameController. |
| Event log and recorder | `src/session.py` | Detects game phase, set play, goal, penalty, online/offline, fall, role change, low battery; manual marks; one recording at a time as JSON lines (telemetry, GameController, events). |
| Control lock | `src/control_lock.py` | One operator drives at a time ("engineer mode"); request and grant between operators. |
| Camera hub | `src/camera_hub.py` | Asks a robot for its camera only while a page shows it (3 s per request, at most once per second). |
| Simulated referee | `src/sim_gc.py` | For hosted sessions: sends GameController v20 packets at 2 Hz; states, goals, halves, penalties from the page. |
| Pages | `src/index.html`, `src/dashboard.html`, `src/fleet.html`, `src/robot.html` | Plain ES modules, no build step, no framework; Three.js from `src/static/`. Shared modules: `static/field_model.js` (field, names, GameController summary), `static/control_bar.js` (STOP and the lock), `static/inspector.js`, `static/circus_view.js` (3D view). |
| 3D renderer | `renderer/` | MuJoCo 3.3.3 and its classic renderer compiled to WebAssembly, replayed on WebGL2: the browser shows the field and the robots exactly as the circus simulator draws them. |
| CLI | `src/oraculum_cli.py` | `status`, `walk`, `stiffness`, `stop`, `lie`, `damp --really`, `resume`. |
| Robot side | `spqrbooster2026` (branch `feature/oraculum-tcm`) | `DebugMessageSender` (telemetry), `DebugCameraSender` (camera on request), UDP joystick input and the STOP / LIE DOWN / DAMP latches in `LowControlBridge`, the latch states in `Root.cpp`. Active only with `useRerun: true`. |
| Hosted sessions | `hosted/` | One Modal sandbox per session (circus, the robot stack, its own gateway); a web launcher with GitHub login (`hosted/launcher/`). |

## 2. Message contract

**Telemetry** (robot → gateway, one JSON object per datagram): `agents[]` with `id`, `team`, `x`, `y`, `angle`
(field frame, metres and radians), `role`, `state` (R running, P penalised, S stopped by the GameController), `battery`
(percent, -1 unknown), `fallen`, `color`, `joints` (MJCF joint name → radians), `latch` ("stop", "lie", "damp" or ""),
`sys` (version, CPU, load, temperature, Wi-Fi traffic, recording); the robot's own `ball` and `obstacles`; debug
`drawings` (circle, box, line, arc, point; metres) and `texts`. A new field always has a default; unknown fields are
ignored (schema: `src/socket_client.py`).

**Joystick datagram** (gateway → robot, UDP 10007): the Booster remote-controller fields (`lx`, `ly`, `rx`, `ry`,
buttons) plus `isManual`. The robot uses them while datagrams keep coming and returns to its own control 500 ms after
the last one. Extra fields: `stop` (STOP latch), `lie` (LIE DOWN latch), `damp` (damping latch), `undamp` (only with a
one-robot STOP: ends a damping).

**Shared state** (`GET /state`): `agents`, the team `ball`, `drawings`, `texts`, `gamecontroller` (state, clock,
score, teams, half, set play, secondary time, phase, penalties per player, packet age and source), `fleet` (robot-code
commit of the gateway, link rate and age per robot IP), `rec` (recording), `lock` (holder name, your request),
`last_event`.

## 3. Views

| View | Page | Content |
|---|---|---|
| Field | `index.html` | 3D view identical to circus, or 2D arena; one label per robot; debug drawings with a checklist; each robot's own ball estimate and obstacles; robot cards with a team summary ("7/7 online · 1 fallen · …"); inspector; manual joystick. |
| Dashboard | `dashboard.html` | The same data in an IDE-like layout with docks. |
| Fleet and events | `fleet.html` | One row per robot: role and state, software version against the gateway's checkout, CPU, load, temperature, battery, Wi-Fi traffic, link; STOP / Resume / LIE DOWN per row; event log with filters and marks; recordings with download; the simulated referee's buttons in a hosted session. |
| Robot | `robot.html` | The robot's camera with its detections and the field lines projected from its own pose (a quick localisation check); its world model; STOP / Resume / LIE DOWN, and DAMP behind a locked danger section. |
| Launcher | `hosted/launcher/launcher.html` | Start and stop a personal simulation session; links to its oraculum, its referee and its circus window. |

All pages poll `/state` (no WebSockets) and work on phones. A page greys the robot data and says so when the data is
older than 3 s.

## 4. Safety and engineer mode

- **STOP** (STOP ALL in every header, STOP per robot): the robot's STOP latch; the robot holds until Resume.
  Open issue: on a walking robot the switch to the firmware's Prepare pose made the robot fall in the simulator.
- **LIE DOWN** (hold 2 s): the firmware lays the robot on its back. Open issue: the simulated firmware refuses it
  (lie-down disabled in its configuration).
- **DAMP** (motors soft; the robot falls and can break): one robot at a time, only on the robot page after typing its
  name and holding 3 s; the gateway refuses it for all robots and without confirmation. A damped robot cannot walk
  again directly: lift it, press its STOP (it stands), then Resume.
- STOP, LIE DOWN and DAMP need no lock and pass the GameController rule. Each sends three datagrams 0.1 s apart and
  writes an event with the operator's name. The page shows "sent"; the robot's own latch in its telemetry shows the
  result (STOPPED, LYING, DAMPED badges).
- **Engineer mode:** manual driving and Resume need the control lock. A free lock goes to the first operator; a held
  lock moves only when its holder grants a request or releases it, or when the holder's page has been closed for 15 s.
- **Referee rule:** in READY, SET and PLAYING the gateway refuses manual commands unless an engineer enables the
  bypass in their own tab.

## 5. Hosted simulation sessions

One sandbox per session on Modal holds circus (headless on a virtual display, software OpenGL), the robot stack
(Booster motion controller, simbridge, Maximus) and its own gateway with a simulated referee. Only HTTPS leaves the
sandbox: the gateway and a browser view of the circus window. Each session has its own access token; outbound network
is blocked; joystick datagrams can only reach the session's own robot.
The launcher on the team server signs people in with GitHub (SPQRTeam members only), starts and stops sessions and
logs the use per person. Limits: 2 sessions at a time, 30 minutes each, 10 minutes without an open page, a daily cost
cap.

Measured (2026-10-19, one robot, 4 cores requested):

| Quantity | Value |
|---|---|
| Real-time factor of the simulation | 0.98 (59 s simulated per 60 s) |
| CPU use | about 4.5 cores (circus simulator and its window 2.3, simbridge 1.0, Maximus 0.7, motion controller 0.5) |
| Memory | 1.3 to 2 GB |
| Start time from a cached image | 1.3 s to create the sandbox; robot telemetry after about 10 s |
| Cost | about $0.70 per session-hour, checked against the provider's bill; capped at $0.85 per hour by the limits |

## 6. Running it

```bash
python3 run_oraculum.py                  # gateway on :8080 and the main page
python3 tools/udp_sender.py              # 7 simulated robots (no robot needed)
python3 src/oraculum_cli.py status
```
On a robot: `useRerun: true` in `deploy.yaml`, then `pixi run deploy` from `spqrbooster2026`. Telemetry goes to the
gateway's address (`ORACULUM_HOST` overrides it).

## 7. Limitations and open work

- STOP on a walking robot and LIE DOWN (section 4).
- The robot side is not yet tested on a real robot.
- The 3D view needs WebGL2 and a GPU for a smooth frame rate; the 2D view works everywhere.
- Hosted sessions run one robot today; more robots need more cores per session.
