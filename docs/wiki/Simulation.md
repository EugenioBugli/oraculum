# Simulation

Result first: there are three ways to test oraculum without real robots.

| Way | Robots | Where | Status |
|---|---|---|---|
| Fake robots | `tools/udp_sender.py`: 7 robots that move at random. No robot code runs. | Your laptop | Tested in simulation (2026-10-21). See [Quick Start](Quick-Start). |
| Local circus | circus (the team's MuJoCo simulator) with the real robot code (Maximus, booster-motion, simbridge) in Docker. | Your PC | Not tested with the oraculum settings of this wiki. |
| Hosted session | The same stack on a rented server (Hetzner Cloud), reached through an SSH tunnel. | A Hetzner server | Tested in simulation (2026-10-21) with up to 10 robots. |

In all three ways, the robot code in simulation used `useRerun: true` until 2026-10-21. **`oraculum: "practice"` and
`"match"` have not run in simulation yet.**

## Local circus

Run these in the `spqrbooster2026` checkout (branch `oraculum-tcm`). circus is a desktop app: it needs a display.

```bash
pixi run sim 1v1
```

- `pixi run sim <scene>` starts circus with a scene from `src/app/sim/` and one Docker container per robot.
- The robot code in simulation reads `deploy.yaml` and `settings.yaml` from your checkout. Set `oraculum: "practice"`
  as on the field. In simulation, an empty `oraculumHost` makes the robot send to the host of `rerun.connectAddr` in
  `connect` mode, else to the broadcast address of its network.
- Start the gateway on the same PC: `python3 src/control_server.py` in the oraculum folder.
- The robots need a referee. Use the official GameController (`pixi run -e gc gc-spqr` in `spqrbooster2026`), or the
  oraculum simulated referee. The simulated referee sends to `127.0.0.1:3838` by default. Robots in Docker containers
  need their container IPs in `ORACULUM_GC_TARGETS`:

  ```bash
  ORACULUM_SIM_GC="19,2" ORACULUM_GC_TARGETS="<robot IP 1>,<robot IP 2>" python3 src/control_server.py
  ```

- `scenario` in `settings.yaml` must be `sim_fast` in simulation. `real` stops Maximus with no error line on a PC with no
  GPU (see [Known Issues](Known-Issues)).

Status: not tested with a real robot, and not run in simulation with the settings of this wiki. The commands come from
the `spqrbooster2026` notes and the code.

## Hosted sessions on Hetzner Cloud

A hosted session is one rented server that runs circus, the robots and its own gateway with the simulated referee.
The files are in `hosted/` and `hosted/vm/`. `hosted/HETZNER.md` has the full notes.

### How a session works

1. Create a server from the prepared image (the "golden snapshot"): `python3 hosted/hetzner.py create NAME --type ccx43 --image <snapshot id>`.
   Without `--yes` the script only prints the price. Add `--yes` to create the server.
2. The service `oraculum-sim` starts a session at boot (`hosted/vm/vm_session.sh`): a virtual display, a browser view of
   the circus window (noVNC on port 6080), the gateway with the simulated referee on port 8080, and circus.
3. Open an SSH tunnel and use the pages on your laptop:

   ```bash
   ssh -L 8080:localhost:8080 -L 6080:localhost:6080 root@<server IP>
   ```

   Then open `http://localhost:8080/?token=<token>`. The server writes a new access token at each boot
   (see `hosted/vm/vm_session.sh`). Do not publish ports 8080 or 6080 without TLS: the token is in the URL.
4. The robots stay in INITIAL until somebody uses the referee menu on a page.
5. Delete the server: `python3 hosted/hetzner.py delete NAME`. **Hetzner bills a server for every started hour while it
   exists, also when it is off.** Only delete stops the bill.

Other commands of `hosted/hetzner.py`: `prices`, `list`, `images`, `snapshot NAME "description"`, `reap --max-minutes N`,
`sshkey-add NAME PATH`. A timer on a team server deletes every session server older than 3 hours.

To build a new golden snapshot, follow "Build order" in `hosted/HETZNER.md` (`hosted/vm/push.sh`, then
`provision.sh` on the server, a smoke test, `hetzner.py snapshot`, `hetzner.py delete`).

### Differences from the field

- The camera is off (circus runs with `--no-images`). The robot page shows no image.
- The servers unpin the robots' motion controller from CPU 3 (see [Known Issues](Known-Issues)). Real robots keep the
  pin.
- `provision.sh` forces `scenario: "sim_fast"`.
- The service restarts the match every hour, because Maximus memory grows (about 18 MB per minute per robot, measured
  on Modal).

### Measured real-time factors

The **real-time factor** is simulated seconds divided by wall-clock seconds. 1.0 is real time. Below 1 the robots move
in slow motion. Measured on 2026-10-21 with `hosted/vm/measure_rtf.sh`:

| Game | Server | circus time step | Real-time factor |
|---|---|---|---|
| 1v1 | CCX33 (8 dedicated vCPU) | 2 ms | 0.98 |
| 3v3 | CCX33 | 2 ms | 0.45 |
| 3v3 | CCX33 | 4 ms (test edit) | 0.77 |
| 5v5 | CCX33 | 2 ms | 0.18 |
| 1v1 / 3v3 / 5v5 | CPX62 (16 shared vCPU) | 2 ms | 0.95 / 0.44 / 0.22 |
| 5v5, motion controller unpinned | CPX62 | 2 ms | 0.34 (40 s run) |

- The factor falls about as 2/N with N robots. More cores do not fix it: 45–65 % of the CPU was idle.
- The robots fall when the simulation runs clearly below real time, and they do not get up. A stable 3v3 or 5v5 needs
  a factor near 1.

### Costs

| Item | Cost |
|---|---|
| CCX33 server | 2 started hours = EUR 0.54 incl. VAT (2026-10-20/21). |
| CCX43 server (16 dedicated vCPU) | EUR 0.4431 per hour excl. VAT. |
| Golden snapshot | EUR 0.0143 per GB per month; the 7.0 GB snapshot costs about EUR 0.10 per month. |

`python3 hosted/hetzner.py prices` reads the live prices.

## Hosted sessions on Modal (earlier)

`hosted/modal_session.py` runs a one-robot session in a Modal sandbox (a cloud container service). A web launcher
(`hosted/launcher/`) behind a GitHub login for SPQRTeam members starts these sessions. It allows 2 sessions at once,
1 per user, 30 minutes per session and USD 3 per day in total. A session uses 4–5 CPUs and 4–6 GiB of memory and stops
after 10 minutes without use.

```bash
python3 hosted/modal_session.py start --minutes 25
python3 hosted/modal_session.py stop sb-...
```

The play tests of 3v3 and 5v5 games ran on Hetzner, not on Modal.
