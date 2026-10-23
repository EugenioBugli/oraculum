# Known Issues

Status 2026-10-21. Each issue says where the finding comes from: **from code** (read in the source), **measured**
(seen in a run) or **estimated** (computed, not seen).

## 1. Nothing is tested with a real robot

The first session with real robots is on 2026-10-22. Treat every robot-side behaviour in this wiki as unconfirmed.

## 2. Older robot builds ignore the `oraculum` settings

`oraculum` and `oraculumHost` exist from `spqrbooster2026` commit `d55b0946` (branch `oraculum-tcm`, pushed 2026-10-21).
Deploy `bc462d43` or later (GET UP, GO TO, SIT and MANUAL with `customMode: false`).
A robot that runs an older build ignores them. With `useRerun: false` it then sends nothing and shows no error. Check
the version column of the fleet table. The changes compile and link for x86; the aarch64 robot build is not tested.
See [Field Setup](Field-Setup). (from code)

## 3. Match mode: oraculum cannot stop a robot

In match mode the robot does not listen on UDP 10007. The gateway knows this from `sys.link = "telemetry"` and refuses
STOP, LIE DOWN, DAMP, Resume, Get up, Sit down and Go to with HTTP 409; the page shows the error text. MANUAL
(`POST /control`) is **not** refused for such a robot: the gateway sends the joystick datagrams and the robot ignores
them. With the gateway match switch, every command is refused. A robot in match mode can only be
stopped with its own remote controller or through the referee. (from code; the refusal is not tested with a real robot)

## 4. Match mode: 1 packet per second and the 3.5 s timeout

The gateway drops a robot 3.5 s after its last packet (`src/socket_client.py`; it was 2 s before 2026-10-21). In match
mode the robot sends every 1 s, so one lost packet does not drop it. Three lost packets in a row make the robot
disappear from the field view and the TV for a moment, and the event log gets an OFFLINE and an ONLINE event.
The fleet table keeps an offline robot for 60 s. (from code, not measured)

## 5. Match mode and the "wired network" rule

The gateway match switch (`ORACULUM_MATCH=1`) is tested in-process and in a browser with fake robots, not at a venue.

The HSL rule allows debug packets only "to a single team device on the wired network". Nobody has checked how the
laptop connects at a venue. See [Match Mode and Rules](Match-Mode-and-Rules). (from the rule text)

## 6. `deploy.sh` does not warn about oraculum

- A plain `pixi run deploy` with `oraculum: "practice"` prints no warning. Only `useRerun: true` gets the
  "Disable it before competition" warning. (from code)
- `deploy-match` does not check that `oraculumHost` is set. Without it, the robot sends no telemetry, and you see this
  only in the robot log. (from code)
- `deploy-match` with `oraculum: "off"` gives no telemetry at all. (from code, checked with `yq` on a sample file)

## 7. Team messages stop when the message budget is low

`TeamMessageSender` sends only while the budget that the GameController announces is above
`messageBudgetSafetyThreshold` (`respectMessageBudget: true`).

- `oraculum-tcm` at `bc462d43` (based on `mappazzone`, the code to deploy): threshold 150, one message every 600 ms
  (`src/app/config/settings.yaml`). (from code)
- An older `mappazzone` state had threshold 5000 and 180 ms. A team of 5 then reached the reserve after about 252–280 s
  of counted game time and sent no team messages after that. (estimated) Check the values in the build you deploy.
- Before the first GameController packet the announced budget is 0, so a robot without a GameController never sends a
  team message. (from code)
- The simulated referee of oraculum always announces 12000 and never counts down, so the simulation cannot show this.
  (from code)
- At 600 ms a team of 5 sends about 10,800 messages in a game, about 1,050 below the 11,850 that a reserve of 150
  leaves. (estimated)
- Open point for the `mappazzone` authors: also send when no GameController is present.

## 8. `scenario: "real"` stops Maximus in the simulator

`mappazzone` and `oraculum-tcm` at `bc462d43` commit `scenario: "real"` in `settings.yaml` (`main` has `sim_fast`). In the hosted 5v5 simulation,
Maximus stopped while it created the Perception node, with no error line, and no robot sent telemetry. (measured)
The code points to the object detector, which always asks for the GPU, on a server with no GPU. This is an inference:
the exit signal was not captured.

- No effect on real robots: `deploy.sh` forces `scenario: "real"` at deploy time, and the robots have a GPU. (from code)
- On a PC with a GPU, `real` in the simulator still blocks play: the robot waits for the joystick Play combo. (from code)
- The hosted scripts force `sim_fast`. In your own simulation, set `scenario: "sim_fast"`.

## 9. The robots' motion controller is pinned to CPU 3

`booster-motion` (the closed Booster binary that runs the walking controller) pins its real-time control thread to
CPU 3. In a simulation with 10 robots, all 10 control threads share core 3. (measured: seen live)

- Unpinning them after start raised the 5v5 real-time factor from 0.22 to 0.34. (measured, 40 s, CPX62)
- The hosted servers unpin them (`hosted/vm/vm_session.sh`). The robot image and the real robots keep the pin
  (decision of 2026-10-21).
- The unpin loop has not run inside a full session yet.

## 10. Multi-robot simulation runs slower than real time

The real-time factor falls about as 2/N with N robots: 0.98 (1v1), 0.45 (3v3), 0.18–0.22 (5v5). (measured)

- It is not a CPU shortage: 45–65 % of the CPU was idle, and 16 cores gave the same result as 8.
- Each robot adds about 0.9 ms of wall time to every 2 ms physics step. The rest of this cost is not found yet. The
  suspect is the robot side (booster-motion or simbridge answer time per step).
- Below real time the robots fall and do not get up. A 4 ms time step gave 0.77 for 3v3 (test edit only).
- Maximus memory grows about 18 MB per minute per robot (measured on Modal). The hosted service restarts the match every
  hour.

## 11. UI and CLI limits

- The on-screen joystick cannot turn the robot: the pages always send `vtheta: 0`. Use `oraculum_cli.py walk`. (from code)
- The speed sliders go up to 2.0, but the robot clamps each stick value to [-1, 1]. Above 1.0 a slider has no effect.
  (from code)
- The ARMS: LIMP button in the main view and the IDE-style view sends `lt`, which the robot reads only as the left
  trigger. It does not make the arms limp. (The CLI command `stiffness` with the same problem was removed on
  2026-10-21.) (from code)
- The reply "sent" to STOP does not mean that the robot stopped. Only the `latch` value in the robot's next
  telemetry shows it (STOPPED in the fleet row). (from code)

## 12. Camera not tested

`DebugCameraSender` is not tested on a robot or in the simulator. The hosted sessions run circus with no camera images.
(from code)
