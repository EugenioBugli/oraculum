# Safety Controls

Result first: STOP makes a robot stand still. LIE DOWN puts it on the ground in a controlled way. DAMP makes the motors
soft, and **the robot falls**. Resume lets the robot play again. MANUAL lets one operator drive one robot.

**Status: none of these controls is tested with a real robot.** The gateway side and the fake robots
(`tools/udp_sender.py`) are tested in simulation (2026-10-21). The project notes record that the STOP latch also works with circus robots in simulation (with `useRerun: true`).

> **Match mode: oraculum cannot stop the robot.** With `oraculum: "match"` in `deploy.yaml`, the robot does not listen
> on UDP 10007. The gateway refuses the command with HTTP 409 and the page shows "This robot is in match mode".
> In match mode, stop a robot with its own remote controller or through the referee.
> See [Match Mode and Rules](Match-Mode-and-Rules).

## How the commands reach the robot

- The gateway sends each safety command as a small JSON datagram to UDP 10007 of the robot, **3 times, 0.1 s apart**.
  One lost Wi-Fi packet does not lose a STOP.
- The robot reads it in `LowControlBridge` (practice mode only) and sets a **latch** (a state that stays on until it
  is cleared). The robot reports the latch in its telemetry: `latch` = `stop`, `lie`, `damp` or empty.
- The page says "sent" when the gateway has sent the datagrams. The robot does not confirm. Look at the fleet row or
  the robot page: it shows STOPPED, LYING or DAMPED when the robot reports the latch.
- STOP, LIE DOWN and DAMP need no control lock, and they work in every game state (also during PLAYING).
- "All robots" means every robot IP that sent telemetry in the last 60 s. A single robot must be an IP that sends
  telemetry. With no target, the gateway answers HTTP 409.

## The commands

| Command | What the robot does | How to clear it | Where |
|---|---|---|---|
| **STOP** | Stands in the Prep pose (the standing-ready pose). | Resume (the Play combo) or the Manual combo. | STOP ALL in every page header; STOP on each robot card and fleet row; `oraculum_cli.py stop --ip IP` or `--all`. |
| **LIE DOWN** | The firmware lays the robot on its back. This is the controlled way to the ground. A later STOP keeps it down. | Resume or the Manual combo. | 2 s press-and-hold in the fleet row and on the robot page; `oraculum_cli.py lie --ip IP` or `--all`. |
| **DAMP** | The motors go soft. **The robot falls and can break.** | Lift the robot, press STOP for this robot, then Resume. | Only on the robot page, in the closed "Danger" section: type the robot's name, then hold for 3 s. `oraculum_cli.py damp --ip IP --really`. |
| **Resume** | The Play combo (RB+RT+A of the remote). The robot plays again. | — | Resume on each robot card and fleet row; `oraculum_cli.py resume --ip IP` or `--all`. |

Rules for DAMP:

- DAMP goes to one robot only, never to "all". The gateway refuses it without `confirm` equal to the robot's IP.
- A STOP for **one** robot also ends its DAMP: the robot stands up into the Prep pose. STOP ALL never ends a DAMP,
  so it never raises a robot that was damped on purpose.
- The gateway refuses Resume for a damped robot (HTTP 409), because the firmware refuses to go from damping to walking.
  Lift the robot, press its own STOP, then Resume.

The robot's own remote controller also clears the latches: the Play combo (RB+RT+A) and the Manual combo (RB+RT+B)
clear STOP, LIE DOWN and DAMP. The firmware Prep combo (LT+START) clears only DAMP.

## Control lock (engineer mode)

Only one operator at a time may drive a robot. The **control lock** decides who.

- The lock covers MANUAL driving and Resume. It does not cover STOP, LIE DOWN, DAMP or the TV director.
- A page takes a free lock with its first manual command, or with **Take** in the header.
- When another operator holds the lock, you can ask for it. The holder sees your request and can grant or deny it.
- The holder's page keeps the lock alive. After 15 s with no request from the holder's page, the lock is free.
- After you release the lock, your own commands do not take the free lock again for 15 s. Press Take to take it at
  once. This stops a late command from a page that has just given up control.
- A command without the lock gets HTTP 423 ("<name> has control").
- The CLI is one client per run. It releases the lock when it ends.

## MANUAL (on-screen joystick)

MANUAL drives one robot with the on-screen stick of the main view.

1. Select the robot on the field. Status: tested in simulation (fake robots).
2. Tick MANUAL. The page takes the control lock if it is free. Status: tested in simulation (fake robots).
3. Drag the stick. The page sends a command every 80 ms while MANUAL is ticked and you hold the lock.
   Status: not tested with a real robot.
4. Untick MANUAL when you are done. Status: tested in simulation (fake robots).

- The stick sets forward speed (`vx`) and sideways speed (`vy`). The sliders scale them. The robot multiplies them by
  its own top speed and clamps each stick value to [-1, 1], so a slider above 1.0 has no more effect.
- **The on-screen stick cannot turn the robot**: the pages always send `vtheta: 0`. To turn, use the CLI
  (`oraculum_cli.py walk VX VY VTHETA --ip IP`).
- The robot uses the oraculum joystick only while datagrams keep arriving. **500 ms after the last one, it goes back to
  its own remote controller.** A closed browser cannot leave the robot walking.
- The robot that MANUAL drives is fixed when you tick MANUAL. Selecting another robot only shows it.
- A yellow banner names the robot while MANUAL is on.
- **ARMS: STIFF / LIMP** sends the `lt` field. On the robot, `lt` is only the left trigger of the joystick now.
  It does not make the arms limp.

## Referee rule

During READY, SET and PLAYING the gateway refuses manual commands (HTTP 403). The page does not send them and says why.

- **Bypass referee rules** (main view menu, with a confirmation dialog) lets MANUAL commands through. It is for tests
  with the GameController running. Every page then shows a red chip with the operator name for 5 s after each command.
- STOP, LIE DOWN and DAMP are never blocked by this rule.
- In an official match the robots must be autonomous. Do not drive a robot in a match. In match mode the robot ignores
  all commands anyway.
