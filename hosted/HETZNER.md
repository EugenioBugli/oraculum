# Hosted sessions on Hetzner Cloud (circus native Docker mode)

Status 2026-10-21: built on a CCX33 (`provision.sh` took about 4 min, not 35-60) and smoke-tested with 2 robots
(`scenes/1v1.yaml`): native Docker mode works (no GPU hang), telemetry from both containers reaches the gateway at
10 Hz, the simulated referee reaches them, both robots walk, real-time factor 0.98 (60 s in 61.4 s). CPU with 2 robots
walking: circus 1.6 cores, per robot about 1.2 cores (booster-motion 0.6-0.7, simbridge 0.3 at the 200 us poll,
Maximus 0.2-0.3). So 10 robots need about 12 cores plus circus: CCX43 (16) is tight, CCX53 (32) has headroom.
Phone access: a Cloudflare quick tunnel (`cloudflared tunnel --url http://localhost:8080` on the VM) worked on
2026-10-20 with the user's explicit permission; ask again for each new tunnel.
Hetzner bills a server for every started hour while it exists, also when it is off; only delete stops the bill.
A session is: create a server from the golden snapshot, run, delete. The snapshot costs EUR 0.0143/GB/month.

| File | Runs on | Does |
|---|---|---|
| `hetzner.py` | laptop or controller | create (dry run without `--yes`), delete, snapshot, list, reap, prices, sshkey-add |
| `vm/push.sh root@<ip>` | laptop | copies the sources straight to the VM (no local staging: both disks are full) |
| `vm/provision.sh` | VM | installs Docker CE + pixi, builds the robot image, circus and Maximus, sets the robot config |
| `vm/vm_session.sh` | VM (systemd) | display, noVNC, gateway + simulated referee, circus `--no-images` |
| `vm/cleanup.sh` | VM (systemd) | removes leftover robot containers, `CIRCUS_network`, `/dev/shm/circus_ipc` |
| `vm/oraculum-sim.service` | VM | runs a session at boot; a new match every hour (Maximus memory growth) |
| `vm/measure_rtf.sh` | VM | real-time factor: simulated seconds / wall seconds, plus a CPU snapshot |
| `scenes/1v1.yaml`, `scenes/5v5.yaml` | VM | 2-robot smoke test; full game (teams 1 and 2) |

## Play tests 2026-10-21 (CCX33, 8 dedicated vCPU; robot code = mappazzone + our oraculum commits)

| Game | circus timestep | Real-time factor | Roles | Falls |
|---|---|---|---|---|
| 1v1 | 2 ms (48154ea1) | 0.98 | Striker each (alone per team) | none in 90 s |
| 3v3 | 2 ms | 0.45 | Goalie / LeftGuard / Striker, dynamic | from 15 s, most down by 100 s |
| 3v3 | 4 ms (test edit on the VM) | 0.77 | Goalie / LeftGuard / Striker | from 30 s |
| 5v5 | 2 ms | 0.18 | Goalie / guards / Striker / PassiveStriker | from 40 s, most down by 170 s |

- **Not a CPU shortage (CPX62, 16 shared AMD vCPU, 2026-10-21 09:10-09:40 UTC):** 1v1 0.95, 3v3 0.44, 5v5 0.22 —
  the same as on 8 cores, with 45-65 % of the CPU idle. The real-time factor falls about as 2/N with N robots: each robot
  adds about 0.9 ms of wall time to every 2 ms physics substep. circus's physics thread runs at only 30-40 % of a core
  (it waits for the robots' commands); a smaller virtual screen (640x360) changed nothing. The serial cost per robot is
  not found yet: the circus wait loop (`RobotManager::receiveCommandMessagesSHM`) checks all robots in parallel, so the
  suspect is the robot side (booster-motion / simbridge answer time per substep). More cores or a second server per
  team will NOT fix it.
- **Found (part of it):** booster-motion (closed binary, simbridge `tools/booster_motion/booster-motion`) pins its
  control thread to CPU 3 with SCHED_FIFO 39, hard-coded in `RsGaitApp::initGait` (disassembly). Seen live: all 10
  robots' control threads on core 3. Unpinning them after start (`for p in $(pgrep -x booster-motion); do taskset -a -p
  -c 0-15 $p; done`) raised the 5v5 from 0.22 to 0.34 (40 s, CPX62). Applied on hosted servers only (user, 2026-10-21: the robot
  image and the real robots keep the pinning): `vm/vm_session.sh` runs a loop that unpins each new booster-motion.
  Run inside full sessions on 2026-10-21 afternoon (see the next section). The rest
  of the per-robot cost is not found yet. Do not drop SYS_NICE/IPC_LOCK/Privileged: the control thread exits if its
  real-time setup fails.
- Clips 2026-10-21 (5v5, RTF 0.24): laptop scratchpad of session 968d7df0 (`clips/play5v5*.mp4`); most robots are down
  by 34 s of simulated time.
- Sparse solver test (opt-in, default off): `CIRCUS_JACOBIAN=sparse hosted/vm/push.sh root@<ip>` changes circus's
  `jacobian="dense"` to sparse in `src/SceneParser.cpp`; a push without the variable gives upstream circus back. Not yet
  measured in a match; the laptop benchmark (MuJoCo 3.10, standing robots) gave 10 robots 0.31 ms vs 1.94 ms per step.
- Two-server split prepared but not run (account limit: 8 dedicated cores in total): `circus_split_teams.patch`
  (Docker socket per team + TCP_NODELAY), `vm/split_peer.sh` (server B), `hetzner.py create --network`,
  `CONNECT_MODE` in `vm_session.sh`, `PEER_GC_URL` in `measure_rtf.sh`. The private network `oraculum-split` exists (free).
- Robots fall whenever the simulation runs clearly below real time (booster-motion's controller runs on the wall
  clock), and do not get up. A stable 3v3 or 5v5 needs a real-time factor near 1: more cores, and/or the 4 ms timestep. (Later: robots also fall at 0.95, see the afternoon tests.)
- Fixed tonight: oraculum's simulated referee reported a team-message budget of 1200, below the robots' reserve
  (mappazzone `messageBudgetSafetyThreshold: 5000`), so NO robot sent team messages and every robot played alone as a
  Striker (`src/sim_gc.py` now reports 12000). mappazzone commits `scenario: "real"`, which crashes Maximus in the
  simulator: `provision.sh` now sets `scenario: "sim_fast"`. Maximus took deploy.yaml's team colour (all "red"): it now
  honours circus's TEAM_COLOR (spqrbooster2026 branch `feature/oraculum-tcm-mappazzone`).
- `vm/monitor_play.py` prints roles, colours, motion and falls of every robot every N seconds during a session.
- Reproduce: `SPQR=/home/xps/work/spqr-merge bash hosted/vm/push.sh root@<ip>` (the clone holds branch
  `feature/oraculum-tcm-mappazzone`; the default `SPQR` is the /DATA checkout), then `provision.sh`, then
  `SCENE=/opt/session/3v3.yaml SIM_S=60 /opt/session/measure_rtf.sh`.
- The 4 ms test edited circus on the VM only: `src/SceneParser.cpp` timestep "0.002" → "0.004" and
  `include/SimulationThread.h` `kControlDecimation = 10` → `5`, then `pixi run compile`.
- In the 1v1 the joint motion dropped from 0.5-0.8 rad (first 10 s) to a steady 0.21 rad from 20 s on, with no fall.
  Robot positions were not logged, so "the robots stop playing after a few seconds" is not yet explained.
- Spend 2026-10-20/21 (times from the session log): builder 22:24-22:50 UTC, test server 23:20-00:01 UTC:
  2 started hours of CCX33 = EUR 0.54 incl. VAT. Unfiltered API check at 00:05 UTC: 0 servers, primary IPs, volumes,
  floating IPs, load balancers; 1 snapshot (7.0 GB).

## Play tests 2026-10-21 afternoon (CPX62, 16 shared vCPU, unpin loop on, dense solver)

| Game | Real-time factor | Notes |
|---|---|---|
| 1v1 | 0.95 | |
| 2v2 | 0.91 (0.96 and 0.95 in the two 150 s clip runs) | scene `scenes/2v2.yaml` (new): red (-6,0) (-2,-1), blue (6,0) (2,1) |
| 3v3 | 0.64 | was 0.44 without the unpin loop |
| 5v5 | 0.31 | was 0.22 without the unpin loop |

- **Robots fall even at a real-time factor of 0.95** (2v2: red goalie at 10-20 s, red striker at 30 s). The slow
  simulation is therefore not the only cause of the falls. Cause not found.
- Media on the laptop in `/DATA/RoboCup/oraculum_media_2v2/`: `play2v2_realspeed.mp4` (150.6 s, circus window
  recorded with ffmpeg on the server's virtual screen), gateway recordings `rec_20261021_155412.jsonl` (155 s, 4 robots)
  and `rec_20261021_160213.jsonl` (replay with `tools/replay_rrd.py <rec> --gc`), `rtf_dense_*.log`, `monitor2v2*.log`.
- The sparse solver run (`sparse.sh`: rebuild circus with `jacobian="sparse"`, 2v2 and 5v5 for 40 s each) did not
  finish inside the hour. The hard-stop timer deleted the server at 16:43 UTC with no sparse result. Still not measured.
- First provision failed with exit 100: unattended-upgrades held the dpkg lock at boot. Wait for the lock, then run
  `provision.sh` again; check that `ffmpeg` is installed before a clip.
- Spend: CPX62 costs EUR 0.2083/h net, 0.2541/h incl. VAT. The hard stop deleted the server at about the 60-minute
  mark, so the bill is 1 or 2 started hours (EUR 0.25 or 0.51 incl. VAT; not checked on the invoice).
  `hetzner.py list` after the delete: no session servers.

## Session 2026-10-22 (CPX62, live 2v2 for the robot-session day)

- **Robot code decides the frame.** `oraculum-tcm` (based on main 0f8e451b; PR #169 was closed unmerged) takes its pose
  from `OracleBridge` in circus world coordinates, but the blue team's behaviour still assumes its own goal at -x: blue
  defends red's goal and all 4 robots crowd at one goal ("robots get stuck"). With that build the gateway needs
  `frames.mirror_team_color: ""`. `mappazzone` sends each team's own frame: keep `"blue"`. Real robots: own frame, keep `"blue"`.
- **1 h runtime limit.** `RuntimeMaxSec=1h` (Maximus grows about 18 MB/min per robot) stopped the session at 12:06 UTC and
  the stop hung in "deactivating (final-sigterm)". For the day: drop-in
  `/etc/systemd/system/oraculum-sim.service.d/no-limit-today.conf` (`RuntimeMaxSec=infinity`); 4 robots grow about
  4.3 GB/h of 32 GB (estimate). Delete the drop-in to get the limit back.
- **Reset button.** The unit sets `ORACULUM_RESTART_CMD`; the pages show "Reset session" in the GC panel (two clicks),
  `POST /session_restart` restarts the service: robots, ball and referee back to the start in about 100 s (tested).
- **Slow uplink.** Pushes from the laptop run at 150-200 KB/s (simbridge tarball 113 MB: about 12 min). The 3D scene over the
  tunnel downloads at about 2 MB/s; `b2.js` now fetches 4 files at a time so `/state` keeps answering (was 2-3.6 s).
- circus also has console commands `mvr <team> <id> <x> <y> <deg>` and `mvb <x> <y>` (its own window, via noVNC on 6080).

## Safety net (deployed 2026-10-21)

The orchestrator droplet (`root@100.65.179.42`) runs `/opt/oraculum-reaper/hetzner.py reap --max-minutes 180` every
10 minutes (`/etc/cron.d/oraculum-reaper`, log `/var/log/oraculum-reaper.log`, token `/root/.config/hcloud/oraculum.token`
mode 600). Any server labelled `oraculum=session` older than 3 h is deleted; other servers and snapshots are never
touched. Change the cap in the cron line. State on 2026-10-21 23:00: no servers; only the golden snapshot `446062995`
(7.0 GB, EUR 0.10/month) bills.

(2026-10-22: cap raised to 600 min for the robot-session day; the reaper deleted `oraculum-sim-cpx62` at 20:40 UTC after 608 min; restored to 180 on 2026-10-23.)

## Build order

1. `hetzner.py sshkey-add laptop ~/.ssh/id_ed25519.pub` (once).
2. `hetzner.py create builder --type ccx33` (dry run: shows the price), then the same with `--yes`.
   Build on CCX33: a snapshot boots only on a server whose disk is at least as large (240 GB: CCX33, CCX43, CCX53).
3. `hosted/vm/push.sh root@<ip>`, then `ssh root@<ip> /opt/session/provision.sh` (estimate 35-60 min).
4. Smoke test in the same billed hour: `SCENE=/opt/session/1v1.yaml SIM_S=60 /opt/session/measure_rtf.sh`.
   It checks the GPU skip, telemetry from the containers to the gateway, the Docker firewall and the Qt libraries.
5. `systemctl enable oraculum-sim`, `hetzner.py snapshot builder "oraculum 5v5 <date>"`, `hetzner.py delete builder`.
6. 5v5 test: create a CCX43 from the snapshot, `systemctl stop oraculum-sim`, `SIM_S=120 /opt/session/measure_rtf.sh`.

## Versions

- Default: circus `48154ea1` + simbridge `ce708bfa` (both `main`, 2026-10-18, "t2-integration"). They are a pair:
  the shared-memory layout changed (per-robot schema ids in simbridge `RobotSharedState.hpp`).
  circus `48154ea1` also halves the physics timestep (0.004 s to 0.002 s, 10 substeps per 20 ms control step),
  adds `--no-images`, passes `ROBOT_MODEL=T1` to each container (our entrypoint ignores it: fine for T1) and
  includes the GPU detection fix. The T1 joint names did not change (only collision shapes), so the oraculum 3D view
  is not affected.
- Fallback, the pair spqrbooster2026 `main` pins (2026-10-19): `CIRCUS_REF=ae484b3d SIMBRIDGE_REF=11a4b707`
  (4 ms timestep, GPU fix included). Swap to it first if the gait breaks on the new timestep.
- Maximus: since 2026-10-21 the local branch `feature/oraculum-tcm-mappazzone` (mappazzone + our commits; real
  coordinator). Before: our branch `feature/oraculum-tcm` (base `0f8e451b`) as it is. spqrbooster2026 `main` is 54 commits ahead,
  but none of them is needed for these circus/simbridge versions (its `supervisord.conf` change only drops a TensorRT
  library path; simbridge reads `CONNECT_MODE` and `CIRCUS_SHM_DIR`, which circus sets).
- The Modal sessions stay on their pin: `circus_process_robots.patch` touches `RobotManager.h` and `AppWindow.cpp`,
  which changed upstream.

## The simbridge poll period (the cause of the 10-robot stall)

circus runs in lockstep: after every physics substep it waits until every robot has written a new command
(`RobotManager::receiveCommandMessagesSHM`, checks every 200 us). simbridge reads the state through a ROS wall timer
whose period upstream is 1 us (`src/bridge_node.hpp`, `socket_recv_timeout` and `sim2frw_period`). That busy-spins one
core per robot: on Modal, 10 robots starved circus and the physics nearly stopped. A 1 ms period would use up to half
of a 2 ms substep and keep the simulation below real time. `push.sh` sets both to 200 us (`SIMBRIDGE_POLL_US`).
Checked offline: the edit matches both `ce708bfa` (lines 98-99) and `11a4b707` (lines 93-94).

## Traps that `push.sh`/`provision.sh` already handle

- circus before `ae484b3d` always asks Docker for an NVIDIA GPU and hangs on a dialog box without one.
  The GPU detection needs Docker Engine 28.2 or newer (API 1.50): Docker CE from download.docker.com.
- The local `spqrbooster2026/external/simbridge` checkout is stale (`d1df86d`) and holds NTFS "IntxLNK" stubs for
  `tools/booster_motion/lib/libfmt.so.8` and `libSDL2-2.0.so.0`: simbridge comes from GitHub, never from the laptop.
- spqrbooster2026 must be at `/workspace` (absolute paths in `supervisord.conf` and the CMake toolchain).
- `pixi run sim` fails (it runs `update-gcdo` against the empty GameController submodule): circus starts directly.
- Team N uses UDP 10000+N and is an IP byte: teams 1 and 2, never 6-9.

## Network and access

- circus network `CIRCUS_network`: bridge `docker-circus`, 172.21.0.0/16, gateway 172.21.0.1, no NAT.
  Player P of team T is 172.21.T.(P+10); its interface `circus0` gives the team broadcast 172.21.255.255.
- Telemetry: with Rerun mode `save`, each robot broadcasts to 172.21.255.255:10006 and the gateway on the host
  receives it. If it does not arrive, add `export ORACULUM_HOST=172.21.0.1` to `/workspace/scripts/docker_entrypoint.sh`.
- The gateway reaches each robot at its container IP (joystick 10007, camera 10008). Do not set `ORACULUM_CONTROL_IP`.
- Referee: the oraculum simulated referee unicasts to the 10 container IPs (stock circus sends no GameController
  packets). The robots stay in INITIAL until somebody uses the GC overlay (any oraculum page).
- Access token: new at each boot in `/run/oraculum/token`. Tests: open only port 22 and use an SSH tunnel:
  `ssh -L 8080:localhost:8080 -L 6080:localhost:6080 root@<ip>`. Do not publish 8080 or 6080 without TLS (the token
  is in the URL). Do not enable ufw: its default deny drops the container-to-host telemetry.

## Capacity

Measured on Modal with 1 robot: Maximus 0.4-0.7 core, booster-motion 0.3-0.5 core, circus about 2.3 cores.
10 robots need about 14 cores or more, and the new 2 ms timestep doubles circus's physics and lockstep work.
First 5v5 test: CCX43 (16 dedicated vCPU, EUR 0.4431/h excl. VAT). Ten real-time booster-motion loops can starve
circus on an overloaded host; `measure_rtf.sh` shows it.

## Not yet verified

Verified 2026-10-21: telemetry from the containers to the gateway, referee packets to the containers, the Qt
libraries. Not verified: the interaction of circus's own game phases with the oraculum referee; get-up after a fall. There is no health check
yet for a circus that hangs on a load error. Team colour: fixed only on spqrbooster2026 branch
`feature/oraculum-tcm-mappazzone`; the golden snapshot `446062995` still has the old build (all robots "red").
