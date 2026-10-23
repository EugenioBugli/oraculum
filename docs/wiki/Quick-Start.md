# Quick Start (one laptop, no robot)

Result: in about 5 minutes you see 7 fake robots, a ball and debug drawings in the browser. You can also test the
referee rules and the STOP button. No robot and no simulator are needed.

**Status of Steps 1–7: tested in simulation (fake robots, `tools/udp_sender.py`, 2026-10-21).** The optional 3D files
section is marked on its own.

## What you need

| Item | Value |
|---|---|
| Python | `python3` 3.10 or newer, with `pyyaml`. |
| Optional | `Pillow` (the `PIL` package), for the fake camera images. Without it, the fake robots send no camera frames. Everything else works. |
| Free ports | TCP 8080, UDP 10006, 10007, 10008, 10009, 3838. Only one gateway can run on one computer: port 8080 is fixed in the code. |
| Browser | Any current browser. The 3D view needs WebGL2. |

You do not need pixi for oraculum. Do not use `pixi run python ...`: the first `pixi run` downloads hundreds of MB.

## Step 1: Start the fake robots

```bash
cd oraculum
python3 tools/udp_sender.py
```

- The script sends one telemetry packet per robot to `127.0.0.1:10006`, 25 times per second.
- It sends 7 robots of two teams (19 and 5), a ball, each robot's own ball estimate and obstacles, and debug drawings.
- It answers camera requests on UDP 10008 with synthetic images.
- It listens on UDP 10007 like a robot. A STOP, LIE DOWN or DAMP from the gateway freezes all fake robots.
  The Play combo (Resume) lets them move again.

## Step 2: Start the gateway

Open a second terminal:

```bash
cd oraculum
python3 run_oraculum.py
```

The gateway starts on port 8080 and opens `http://localhost:8080/index.html` in your browser.
To start the gateway with no browser, use `python3 src/control_server.py`.

## Step 3 (optional): Start the simulated referee

The simulated referee sends GameController packets, so you can test the referee rules without the real
GameController. Stop the gateway (Ctrl+C), then start it like this:

```bash
ORACULUM_SIM_GC="19,2" python3 src/control_server.py
```

- `"19,2"` are the two team numbers. You must give exactly two numbers.
- Each page then shows a referee menu (GC): one button for each game state (Initial, Ready, Set, Play, Finish) and
  one goal button for each team. The labels can change while the UI is being reworked.
- With the simulated referee, the gateway ignores a real GameController on UDP 3838.
  **Never set `ORACULUM_SIM_GC` on the field.**

## Step 4: Open the pages

| Page | Address |
|---|---|
| Field (main view) | `http://localhost:8080/` |
| IDE-style view | `http://localhost:8080/dashboard.html` |
| Fleet, events, recordings | `http://localhost:8080/fleet.html` |
| One robot | `http://localhost:8080/robot.html?robot=1` |
| TV | `http://localhost:8080/tv.html` |
| TV director | `http://localhost:8080/director.html` |

A phone on the same Wi-Fi opens the same pages with the laptop's IP instead of `localhost`.
See [Pages](Pages) for what each page shows.

## Step 5: Try the CLI

```bash
python3 src/oraculum_cli.py status
python3 src/oraculum_cli.py stop --all
python3 src/oraculum_cli.py resume --all
```

`status` prints the referee state, the robots and the drawings. Without a GameController it says so and goes on.
`stop --all` freezes the fake robots.
`resume --all` lets them move again. See [CLI](CLI) for all commands.

## Step 6: Try the referee rule

With the simulated referee running (Step 3):

```bash
curl -s -X POST localhost:8080/gc -H 'Content-Type: application/json' -d '{"state":"playing"}'
python3 src/oraculum_cli.py walk 0.3 0 0 --ip 127.0.0.1
```

The gateway refuses the walk with HTTP 403: no manual command is allowed in READY, SET or PLAYING.
STOP still works in PLAYING. Set the state back with `-d '{"state":"initial"}'`.

## Step 7: Stop

Press Ctrl+C in both terminals. Stop `tools/udp_sender.py` too. If it keeps running, the next gateway shows the
old fake robots.

## Optional: 3D files

The 3D view has three engines. The default engine ("Circus (exact)") and the MuJoCo engine need files that are not
in git. Download them once, with an internet connection:

```bash
tools/fetch_web_assets.sh
python3 tools/fetch_circus_scene.py
```

- `tools/fetch_web_assets.sh` downloads the MuJoCo WebAssembly build (npm package `@mujoco/mujoco` 3.14.0) and copies
  the Booster T1 robot model from a `circus` checkout next to this repository (`../circus`).
- `tools/fetch_circus_scene.py` downloads the circus scene and renderer from a CI release. It picks the release that
  matches the `spqrbooster2026` checkout next to this repository (`../spqrbooster2026`).
- Without these files, the 3D view falls back to simple box robots. The 2D view always works.
- Status: not tested with a real robot, and not run on 2026-10-21 (the files were already present).

## Next

- Real robots: [Field Setup](Field-Setup).
- Circus robots instead of fake ones: [Simulation](Simulation).
