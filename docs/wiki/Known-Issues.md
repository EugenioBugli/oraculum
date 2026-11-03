# Known Issues

Status reviewed 2026-10-29. Findings below distinguish code inspection, historical measurements and estimates. Earlier simulator results are not acceptance of the current hardware build.

## 1. Real-robot acceptance remains incomplete

Robot 6 received the TCM build based on `bc462d43` over Ethernet on 2026-10-26. Service startup and fresh telemetry were verified after resolving a Rerun library mismatch and missing detector model. Physical manual movement was subsequently reported faulty. The proposed WALK-mode/heading correction is built locally but undeployed and unverified. STOP during walking, recovery actions and camera alignment still need hardware acceptance. Later reconnection showed reachable SSH but stale telemetry; current service state must be diagnosed.

## 2. Older robot builds ignore the `oraculum` settings

`oraculum` and `oraculumHost` exist from `spqrbooster2026` commit `d55b0946` (branch `oraculum-tcm`, pushed 2026-10-21).
Deploy `bc462d43` or later (GET UP, GO TO, SIT and MANUAL with `customMode: false`).
A robot that runs an older build ignores them. With `useRerun: false` it then sends nothing and shows no error. Check
the version column of the fleet table. The AArch64 build was deployed and produced telemetry on robot 6; this does not establish motion acceptance.
See [Field Setup](Field-Setup). (from code)

## 3. Match mode: oraculum cannot stop a robot

In match mode the robot does not listen on UDP 10007. The gateway knows this from `sys.link = "telemetry"` and refuses
STOP, LIE DOWN, DAMP, Resume, Get up, Sit down and Go to with HTTP 409; the page shows the error text. MANUAL
(`POST /control`) is also refused for that target, including when its address is pinned by the gateway. The pages hide its robot commands and disable Manual. The refusal is covered by mocked UDP tests. With the gateway match switch, every command is refused. A robot in match mode can only be
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

- Hold-to-turn buttons are now present in Field and Dashboard, but their effect has not been accepted on a real robot.
- Field/Dashboard speed sliders now stop at 1.0, matching normalized stick limits. Their physical effect still depends on the robot's manual limits and gait controller.
- Field/Dashboard no longer expose an ARMS: LIMP action. The old `lt` mapping did not implement stiffness control; do not use it as a stiff/unstiff command. SIT is also omitted from the selected-robot panel because installed SDK support is unverified.
- The reply "sent" to STOP does not mean that the robot stopped. Only the `latch` value in the robot's next
  telemetry shows it (STOPPED in the fleet row). (from code)

## 12. Camera not tested

`DebugCameraSender` is not tested on a robot or in the simulator. The hosted sessions run circus with no camera images.
(from code)

## Operations adapters (3 November 2026)

Build/stage, deploy/rollback, service and existing network-profile jobs are implemented, with [explicit configuration and verification limits](../OPERATION_JOBS.md). No production simulator image is configured by default. Real SSH/service/NetworkManager recovery and the new framework port still require hardware acceptance. Job success reports process/service/hash evidence, not completed physical movement. SIT and LIE DOWN are unavailable on the current port.
