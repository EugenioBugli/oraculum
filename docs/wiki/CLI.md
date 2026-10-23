# CLI

`src/oraculum_cli.py` checks and commands the robots from a terminal. It talks to the gateway at
`http://localhost:8080`, or at the address in the environment variable `ORACULUM_URL`.

**Status: all commands below are tested in simulation (fake robots, 2026-10-21). None is tested with a real robot.**
The `ORACULUM_ACCESS_TOKEN` and `ORACULUM_URL` support is new on 2026-10-21 and tested with one `stop --all` call.

Environment variables:

| Variable | Effect |
|---|---|
| `ORACULUM_URL` | The gateway address. Default `http://localhost:8080`. |
| `ORACULUM_ACCESS_TOKEN` | The access token of the gateway. The CLI sends it as the `oraculum_token` cookie. Without it, a gateway with a token answers every command with HTTP 401. |

```bash
ORACULUM_URL=http://10.0.19.10:8080 ORACULUM_ACCESS_TOKEN=<secret> python3 src/oraculum_cli.py stop --all
```

Each run is one client of the control lock. It releases the lock when it ends.

**Known bug:** `status` stops with `KeyError: 'state'` when no GameController packet arrived in the last 2 s
(the gateway forgets the referee state 2 s after the last packet). Use the
fleet page instead, or start the simulated referee. The other commands are not affected.

## Commands

### status

```bash
python3 src/oraculum_cli.py status
```

Prints the referee state, score and clock, one line per robot (ID, x, y, heading, role, state), and the debug drawings.
It crashes when no GameController packet arrived in the last 2 s (see above).

### walk

```bash
python3 src/oraculum_cli.py walk 0.4 0.0 -0.2 --ip 10.0.19.103
python3 src/oraculum_cli.py walk 0.4 0.0 0.0 --ip 10.0.19.103 --duration 2
```

- The arguments are `VX VY VTHETA` (forward, sideways, turn), each from -1.0 to 1.0. The robot multiplies them by its
  own top speeds.
- `--duration` (default 1.0 s): the CLI repeats the command 10 times per second for that time. The robot drops the
  oraculum joystick 500 ms after the last packet, so the robot stops by itself after the run.
- `--ip` (default `127.0.0.1`) and `--port` (default 10007).
- It needs the control lock. It is refused (HTTP 403) in READY, SET and PLAYING.
- This is the only client that can turn the robot. The on-screen joystick always sends `vtheta: 0`.

### stop, lie, resume

```bash
python3 src/oraculum_cli.py stop --ip 10.0.19.103
python3 src/oraculum_cli.py stop --all
python3 src/oraculum_cli.py lie --ip 10.0.19.103
python3 src/oraculum_cli.py resume --ip 10.0.19.103
```

- `--all` = every robot that sent telemetry in the last 60 s.
- `stop` and `lie` need no control lock. `resume` needs it.
- The gateway refuses `resume` for a damped robot (HTTP 409). The help text of `resume` says it clears DAMP; it does not.
  Lift the robot, `stop` it, then `resume`.

### damp

```bash
python3 src/oraculum_cli.py damp --ip 10.0.19.103 --really
```

**The motors go soft and the robot falls.** Hold the robot. Without `--really` the command prints a warning and sends
nothing. `damp` takes one robot only; there is no `--all`.

### No stiffness command

The old `stiffness limp` command is removed (2026-10-21). It only set the joystick's left trigger (`lt`), and the robot
never went limp. To put a robot on the ground, use `lie`. `damp` makes it fall.

## Messages

- `Refused (403)`: the referee state is READY, SET or PLAYING.
- `Refused (401)`: the gateway needs its access token. Set `ORACULUM_ACCESS_TOKEN`.
- `Refused (423)`: another operator holds the control lock, or you released it less than 15 s ago.
- `Refused (409)`: no robot sends telemetry to this gateway, or the robot is damped (resume).
- `Error connecting to Control Server`: the gateway does not run at `ORACULUM_URL`.

## Other tools

| Command | Does | Status |
|---|---|---|
| `python3 tools/udp_sender.py` | Fake robots (see [Quick Start](Quick-Start)). | Tested in simulation. |
| `python3 tools/replay_rrd.py recordings/rec_<date>_<time>.jsonl --gc` | Replays a gateway recording to UDP 10006 in real time. `--gc` also replays the GameController packets; `--speed 2` plays twice as fast. Stop the fake robots first. | Not tested with a real robot; not run on 2026-10-21. |
| `python3 run_oraculum_threaded.py` | The old matplotlib desktop viewer (needs matplotlib and tk). It reads a gamepad on `/dev/input/js0`. | Not tested with a real robot; not run on 2026-10-21. |
| `python3 tools/wasm_check.py` | Headless Chrome check of the 3D view (the gateway and the fake robots must run). | Not tested with a real robot; not run on 2026-10-21. |
