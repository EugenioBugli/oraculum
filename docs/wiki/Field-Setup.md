# Field Setup (real robots)

Result: the robots send telemetry to the oraculum laptop over the field Wi-Fi, and the laptop can send STOP, LIE DOWN,
DAMP, Resume, the joystick and camera requests to them.

**Status: nothing on this page is tested with a real robot.** The first session with real robots is on 2026-10-22.
The `oraculum: practice` and `oraculum: match` settings are new on 2026-10-21. Nobody has run them in simulation
either. The older setting (`useRerun: true`) was tested in simulation with circus robots on 2026-10-21.

The full step list with check boxes is `ROBOT_TESTING_PROCEDURE.md` in the team workspace. This page explains the same
steps.

## 1. Before you start: the robot code

The robot code is `spqrbooster2026` branch `oraculum-tcm`. Since 2026-10-23 it is based on `mappazzone` (the team's
active branch, with team coordination; merge of `RCAP2026-DEV` at `7fb7df9f`). Do not deploy `main` or `mappazzone`:
they have no oraculum link.

> **Code version (2026-10-23).** Deploy `oraculum-tcm` at commit `bc462d43` or later (GitHub branch
> `SPQRTeam/spqrbooster2026` `oraculum-tcm`; the local branch `feature/oraculum-tcm-mappazzone` in
> `/home/xps/work/spqr-merge` has the same commit). It has GET UP, GO TO and SIT (T2 only) over UDP 10007 (`04ef450e`),
> MANUAL that drives also with `customMode: false` (`e7ce3008`), and the remote's Prep combo ends GET UP and GO TO.
> `d55b0946` (2026-10-21) added the settings `oraculum` and `oraculumHost`.
> On the deploy machine: `git fetch origin && git switch oraculum-tcm && git pull`.
> - The changes compile and link for x86 (laptop build, TensorRT off, 2026-10-21). The robot build (aarch64) is not
>   tested yet: the deploy machine makes it. The deploy cross-compile needs the pixi `robot` environment and free disk.
> - Not tested with a real robot.
> - An older commit (`380516b2`) ignores `oraculum:`. With `useRerun: false` it then sends nothing, and it shows no
>   error. On that commit use the old way: `useRerun: true` plus `rerun.connectAddr` (see "Fallback" at the end of this page).

## 2. Network

| Item | Value |
|---|---|
| Robot Wi-Fi address | `10.0.<team>.<100 + player number>`. Team 19, player 3 → `10.0.19.103`. `scripts/deploy.sh` sets it. |
| Robot wired address | `192.168.10.102` on every robot (factory address). Use it only to deploy, one robot at a time. |
| SSH user on the robot | `booster` (`sshUsername` in `deploy.yaml`). |
| Laptop | On the same network as the robots, with a **fixed IP**. You put this IP in `deploy.yaml` (`oraculumHost`). |

Give the laptop a fixed IP before you deploy. The robot sends its telemetry to exactly that address.
If the laptop gets another address later, the robots send to the old one and the pages stay empty.

## 3. Set `oraculum` and `oraculumHost` in deploy.yaml

Edit `spqrbooster2026/src/app/config/deploy.yaml`:

```yaml
useRerun: false
oraculum: "practice"
oraculumHost: "<laptop IP>"
```

The three modes:

| `oraculum` | Telemetry (UDP 10006) | Joystick, STOP, LIE DOWN, DAMP (UDP 10007) | Camera on request (UDP 10008) |
|---|---|---|---|
| `"off"` | Only with `useRerun: true` (old behaviour) | Only with `useRerun: true` | Only with `useRerun: true` |
| `"practice"` | 10 packets per second | Yes | Yes |
| `"match"` | 1 packet per second, to `oraculumHost` only | No | No |

- Keep `useRerun: false`. Practice mode does not need Rerun (the logging tool). `useRerun: true` also starts the Rerun
  logger on the robot; its CPU and Wi-Fi load on a real robot are not measured.
- **Always set `oraculumHost`, also in practice mode.** When it is empty, the robot sends to the host in
  `rerun.connectAddr` (`settings.yaml`). That is a wired `192.168.10.x` address (the committed value, or the address
  that `deploy.sh` detects). Over Wi-Fi, these packets do not reach the laptop.
- Match mode needs `oraculumHost`. Without it, the robot logs "oraculum: match needs oraculumHost in deploy.yaml;
  telemetry off" and sends nothing.
- A value other than `off`, `practice` or `match` stops Maximus at start with an error. Keep the quotes.
- The environment variable `ORACULUM_HOST` (on the robot) changes the target only when `oraculumHost` is empty.
  It is for hosted simulation sessions. Do not use it on the field.

Status: not tested with a real robot (not run in simulation either).

## 4. Deploy

Run these commands on the deploy machine, in the `spqrbooster2026` checkout, with the Ethernet cable to the robot.

One time per robot (see `docs/guides/deploy.md` in `spqrbooster2026`):

```bash
pixi run setup-booster-net
pixi run setup-ssh
pixi run setup-robot
```

For each robot, with the cable connected:

```bash
pixi run deploy -- --number 3 --wifi <FIELD_SSID> --wifi-psk <PASSWORD>
```

- `--number` (the player number) and `--wifi` are required. The script stops without them.
- `--dry-run` prints the plan and stops. `bash scripts/deploy.sh --help` lists all options.
- `docs/guides/deploy.md` shows `-n`, `-r` and `-i`. The current `deploy.sh` rejects these options. Use `--number`.
- pixi passes the options after `--` to the script. This was checked with pixi 0.70.2. The full deploy was not run.
- The deploy cross-compiles into `build/aarch64`. That needs several GB of free disk (not measured).
- The deploy writes `config/version.txt` on the robot: the commit, `+dirty` when the checkout has local changes, and the
  deploy time. The fleet table shows it.

For an official match, use `pixi run deploy-match` instead. See [Match Mode and Rules](Match-Mode-and-Rules).

Status: not tested with a real robot.

## 5. Start Maximus on the robot

- With the robot's own remote: LB+RB+A starts Maximus (service `maximus-start`). LB+RB+X stops it.
- Or over SSH:

  ```bash
  ssh booster@10.0.19.103 '~/spqr/maximus/run.sh start'
  ssh booster@10.0.19.103 '~/spqr/maximus/run.sh status'
  ssh booster@10.0.19.103 '~/spqr/maximus/run.sh logs'
  ```

- In the log, look for this line:
  `DebugMessageSender: Sending debug data to <laptop IP>:10006`.
  In match mode the line ends with ` (match mode, 1/s)`.
- "Disabled, no target" or a wired `192.168.10.x` address means that `oraculumHost` is wrong or empty.
- In practice mode, look also for `DebugCameraSender: Waiting for camera requests on UDP 10008`.

Status: not tested with a real robot.

## 6. Start the gateway on the laptop

```bash
cd oraculum
python3 run_oraculum.py
```

- `config.yaml` needs no change. The gateway listens for telemetry on `0.0.0.0:10006` and for the GameController on
  `0.0.0.0:3838` (all network interfaces).
- `game_controller.own_team` in `config.yaml` must be our team number (19), the same as `team.number` in the robots'
  `settings.yaml`.
- The `joystick` section of `config.yaml` is read only by the old matplotlib viewer. The gateway sends each command to
  the IP of the robot that sends the telemetry.
- Do not set `ORACULUM_SIM_GC` or `ORACULUM_CONTROL_IP` on the field. They are for simulation.
- For an official match, start the gateway with the match switch: `ORACULUM_MATCH=1 python3 run_oraculum.py`
  (or `match: true` in `config.yaml`). It then sends nothing to the robots. See section 11.
- Download the 3D files before you go to the field: they need the internet (see [Quick Start](Quick-Start)).
- The pages assume that robots of the `blue` team send coordinates in their own team frame
  (`frames.mirror_team_color: "blue"` in `config.yaml`). Check on the field that our robots are not drawn mirrored.

Status: the gateway start is tested in simulation. The field network is not tested with a real robot.

## 7. Access token (recommended on a shared network)

Without a token, any device on the field network can open the pages and send STOP, DAMP or joystick commands.
To lock the gateway:

```bash
ORACULUM_ACCESS_TOKEN=<secret> python3 run_oraculum.py
```

- Open each page once with `?token=<secret>`, for example `http://<laptop IP>:8080/fleet.html?token=<secret>`.
  The browser then keeps a cookie (`oraculum_token`) for that gateway.
- Without the token or the cookie, every route answers HTTP 401.
- Run the CLI with the same token: `ORACULUM_ACCESS_TOKEN=<secret> python3 src/oraculum_cli.py status`.
- A TV in kiosk mode keeps `?token=` in its bookmark, because the cookie ends with the browser session.

Status: tested in simulation (2026-10-21, on the laptop and in the hosted sessions). Not tested with a real robot.

## 8. Firewall and ports

If the laptop has a firewall, let in:

| Port | From | What |
|---|---|---|
| UDP 10006 | robots | telemetry and debug drawings |
| UDP 10009 | robots | camera frames |
| UDP 3838 | GameController | referee state |
| UDP 10000 + team | robots | team messages (broadcast; robots on any branch, read-only) |
| UDP 3939 | robots | GameController return packets (only when the robots send them to this laptop) |
| TCP 8080 | phones, other laptops | the pages and the HTTP API |

The laptop sends to the robots on UDP 10007 (commands) and UDP 10008 (camera requests). These are outgoing.
With the gateway match switch on, the laptop sends nothing.
On Ubuntu, `sudo ufw status` shows the firewall state. Status: not tested with a real robot.

The full port list is in [Architecture and Ports](Architecture-and-Ports).

### Robots on other branches show up read-only

A robot that runs a branch without oraculum telemetry (`main`, `mappazzone`, `RCAP2026-DEV`, ...) still shows on every
page: the gateway decodes its team messages (UDP 10000 + team) and, when it sends them here, its GameController return
packets (UDP 3939). Such a robot shows its pose, role, fall state, ball estimate and obstacles, with a tag `TM` or `GC`
and the word **read-only**. Its STOP, Resume, LIE DOWN, panel and DAMP buttons are disabled: it takes no command from
oraculum, and **STOP ALL does not reach it**. Use its remote controller or the GameController. The gateway sends
nothing to it.
Robots of other teams in a format the gateway does not know are only counted (`/state` `reception`).
Status: tested with fake senders in the browser and with robot bytes from the Jetson simulation (`rcap` format).
Not tested with a real robot or with `main` robot bytes.

## 9. Field checklist

Do the checks in this order. Hold or support the robot during every movement check.

| # | Check | How | Status |
|---|---|---|---|
| 1 | Telemetry arrives | `fleet.html` shows the robot, its version and a link rate of about 10 Hz. Or `python3 src/oraculum_cli.py status` (it crashes when no GameController packet arrived in the last 2 s). | Tested in simulation with `useRerun: true`. Not tested with `oraculum: practice`. Not tested with a real robot. |
| 2 | GameController arrives | The referee pill in the main view shows the game state. | Not tested on the field network. |
| 3 | Camera | `robot.html?robot=<ip>` shows frames. | Not tested with a real robot. |
| 4 | STOP | STOP on the robot card or the fleet row (STOP ALL in the page header stops every robot). Or `python3 src/oraculum_cli.py stop --ip <ip>`. The robot stands in its Prep pose. The fleet row shows STOPPED (telemetry `latch` = `stop`). | Not tested with a real robot. |
| 5 | Resume | The Resume button, or `python3 src/oraculum_cli.py resume --ip <ip>`. | Not tested with a real robot. |
| 6 | Manual walk | Tick MANUAL in the main view (you get the control lock), then drive. Or `python3 src/oraculum_cli.py walk 0.4 0.0 -0.2 --ip <ip>`. | Not tested with a real robot. |
| 7 | LIE DOWN | Hold LIE DOWN for 2 s (fleet row or robot page). Or `python3 src/oraculum_cli.py lie --ip <ip>`. | Not tested with a real robot. |
| 8 | DAMP (last) | Robot page, closed "Danger" section: type the robot's name, then hold for 3 s. Or `python3 src/oraculum_cli.py damp --ip <ip> --really`. **The motors go soft and the robot falls.** Hold it. To recover: lift the robot, press STOP, then Resume. | Not tested with a real robot. |

Details of each control: [Safety Controls](Safety-Controls).

## 10. Recording

`fleet.html` (or the Record menu on any page) → Record. The gateway writes `recordings/rec_<date>_<time>.jsonl` in the
oraculum folder. The size limit is 1 GB per recording. Check the free disk space before you record.
Replay later:

```bash
python3 tools/replay_rrd.py recordings/rec_<date>_<time>.jsonl --gc
```

Status: tested in simulation (fake robots, 2026-10-21).

## 11. Match checklist (official game)

The reasons and the rule lines are in [Match Mode and Rules](Match-Mode-and-Rules), section "Network placement in an
official match". Status of every step: not tested at a venue and not tested with a real robot.

| # | Check | How |
|---|---|---|
| 1 | We know the network | Ask the organisers for our IP range and the wired port of our team (HSL L310-311). |
| 2 | Laptop on the wired field network | Cable in, fixed IP from the team range. Wi-Fi off, Bluetooth off (L314). |
| 3 | Robots in match mode | `oraculumHost` = the laptop's wired IP in `deploy.yaml`, then `pixi run deploy-match -- --number N --wifi <FIELD_SSID> --wifi-psk <PASSWORD>`. |
| 4 | Robot log | `DebugMessageSender: Sending debug data to <laptop wired IP>:10006 (match mode, 1/s)`. No `DebugCameraSender: Waiting for camera requests` line. |
| 5 | Gateway in match mode | `ORACULUM_MATCH=1 python3 run_oraculum.py`. No warning about `ORACULUM_SIM_GC` or `ORACULUM_CONTROL_IP` in its output (unset them). |
| 6 | Pages | The header shows "MATCH — no commands". STOP ALL and every robot button are grey. |
| 7 | Telemetry | `fleet.html`: each robot at about 1 packet per second in the Link column. |
| 8 | GameController | The referee pill shows the game state. |
| 9 | No radios near the field | No phone, tablet or Android companion app near the field during the game (L314). |
| 10 | Stop a robot | Only with its own remote controller or through the referee. Oraculum cannot stop it. |

## Fallback: the pushed commit without `oraculum`

Use this only if you deploy a build older than `d55b0946` (see section 1).

```yaml
# deploy.yaml
useRerun: true
```

```yaml
# settings.yaml
rerun:
  mode: "connect"
  connectAddr: "rerun+http://<laptop IP>:9876/proxy"
```

- The robot then sends telemetry to the host in `connectAddr`, and it listens for commands and camera requests.
- `deploy.sh` prints "useRerun is enabled ... Disable it before competition". This is expected for a practice session.
- **Do not use `pixi run deploy-match` with this fallback.** It sets `useRerun: false`, so the robot sends nothing.
- Status: not tested with a real robot. Rerun mode `connect` did not run in simulation either; the simulation tests
  (circus robots, 2026-10-21) used mode `save` with broadcast.
