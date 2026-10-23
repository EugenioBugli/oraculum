# Oraculum

Oraculum is the operator gateway and debug dashboard of team SPQR (RoboCup Humanoid League, Booster T1 robots).
One program, the **gateway**, runs on a team laptop. It collects the data that the robots and the referee send,
and it serves one merged view to every browser, phone and command-line client on the same network.

![Field page with robots](images/field-2d.png)

## What oraculum does

- It shows every robot on a 2D or 3D field: position, heading, role, state, ball estimate and debug drawings.
- It shows the referee state (the **GameController**, the official referee software of the league): game state,
  score, clock, penalties.
- It shows the health of each robot in one table: software version, CPU, temperature, battery, Wi-Fi traffic.
- It shows the camera of one robot on request, with the detections and the field lines drawn over the image.
- It records a session to a file and replays it later.
- It sends safety commands to the robots: STOP, LIE DOWN, DAMP and Resume. It also sends Get up, Sit down (T2 only)
  and Go to a position, from the command panel of the selected robot.
- It lets one operator drive one robot with an on-screen joystick (MANUAL mode), outside the game.
- It drives a public TV screen (scoreboard and field) and a director console for that screen.

## What oraculum does not do

- It does not play. The robots are autonomous. In an official match, oraculum only receives data: start the gateway
  with `ORACULUM_MATCH=1` (see [Match Mode and Rules](Match-Mode-and-Rules)).
- It does not replace the GameController. The simulated referee (`ORACULUM_SIM_GC`) is for tests only.
- It has no desktop app, no mobile app and no WebSocket server. Some older design documents describe these.
  They are plans, not code. Every client is a web page that asks the gateway for the state over plain HTTP.
- It does not read a physical gamepad. Only the old matplotlib viewer (`run_oraculum_threaded.py`) does.

## Test status

Read this before match day. **Nothing has been tested with a real robot yet.** The first session with real robots is
on 2026-10-22. Every procedure step in this wiki carries one of these marks:

| Mark | Meaning |
|---|---|
| **Tested in simulation** | Somebody ran the step with fake robots (`tools/udp_sender.py`) or with circus robots (the team simulator). The date is given. |
| **Not tested with a real robot** | The step comes from the code. Nobody ran it on a robot. Some of these steps did not run in simulation either; the page says so. |

## Pages of this wiki

| Page | Read it when |
|---|---|
| [Quick Start](Quick-Start) | You want to see oraculum work on your laptop in 5 minutes, with no robot. |
| [Field Setup](Field-Setup) | You prepare real robots and the laptop for a session on the field. |
| [Pages](Pages) | You want to know what each web page shows and which controls it has. |
| [Safety Controls](Safety-Controls) | Before you touch STOP, LIE DOWN, DAMP, Resume or MANUAL. |
| [Match Mode and Rules](Match-Mode-and-Rules) | Before an official match. |
| [Simulation](Simulation) | You want circus robots instead of fake ones, on your PC or on a rented server. |
| [Architecture and Ports](Architecture-and-Ports) | You need the data flow, the ports, the HTTP routes or the message format. |
| [CLI](CLI) | You want to check or command robots from a terminal. |
| [Troubleshooting](Troubleshooting) | Something does not show or does not move. |
| [Known Issues](Known-Issues) | Before you trust a result. |

## Code

- Gateway and pages: this repository (`src/control_server.py`, `src/*.html`, `src/static/`).
- Robot side: the `spqrbooster2026` framework ("Maximus"), branch `oraculum-tcm`.
  The parts are `DebugMessageSender` (telemetry), `DebugCameraSender` (camera) and `LowControlBridge` (joystick and
  safety commands). See [Field Setup](Field-Setup) for the branch status.
- Tracking issue: `SPQRTeam/spqrbooster2026#47`.
