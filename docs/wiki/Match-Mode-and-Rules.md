# Match Mode and Rules

Result first: for an official match, deploy with `pixi run deploy-match`. It turns `oraculum: "practice"` into
`oraculum: "match"`. In match mode each robot sends **1 telemetry packet per second to `oraculumHost` only**, and it
accepts **no** command from oraculum: no joystick, no STOP, no LIE DOWN, no DAMP, no camera.

For the laptop, start the gateway with the **match switch** on: `ORACULUM_MATCH=1 python3 run_oraculum.py`, or
`match: true` in `/DATA/RoboCup/oraculum/config.yaml`. The gateway then sends nothing to any robot or to the
GameController. See "The gateway match switch" and "Network placement in an official match" below.

**Status: the robot side is not tested with a real robot (not run in simulation either).** The robot code is new on
2026-10-21. The `deploy.yaml` patch of `deploy-match` was checked with `yq` on a sample file. The gateway match switch
is new on 2026-10-23. It is tested in-process (`python3 tools/test_match.py`) and in a browser with fake robots
(`python3 tools/match_check.py`). It is not tested at a venue.

## The rule

The HSL rules (Humanoid Soccer League rule book) allow debug traffic from the robots only under these conditions
([robot_players.tex, lines 373–374](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L373-L374)):

> Each robot may send debug information in a single UDP packet to a single team device on the wired network.
> The robot may send at most \UDPDebugPacketRate{} packet(s) per second.

`\UDPDebugPacketRate` is 1 (`common/variables.tex`, line 53, same commit). The packet size must stay within one UDP
packet (typically 64 kB). The robots must also play autonomously, so no remote control is allowed during a match.

What match mode does for each part of the rule:

| Rule | Match mode | Checked? |
|---|---|---|
| At most 1 packet per second per robot | `DebugMessageSender` sends every 1000 ms. | From code. Not measured. |
| To a single team device | It sends only to `oraculumHost`, never as a broadcast. Without `oraculumHost`, it sends nothing. | From code. |
| On the **wired** network | The laptop at `oraculumHost` must be on the venue's wired team network. Oraculum cannot check this. | Not checked at a venue. Ask the organisers how the team device connects. |
| One UDP packet, at most about 64 kB | One JSON datagram per robot. Its size with many debug drawings is not measured. | Not measured. |
| Robots autonomous | The robot does not open UDP 10007 (commands) or UDP 10008 (camera). | From code. |

Do not claim that match mode obeys the rule until somebody checks the wired-network part and the packet size at the
venue.

## How to deploy for a match

1. Keep `oraculum: "practice"` and set `oraculumHost: "<laptop IP on the wired team network>"` in `deploy.yaml`.
   Status: not tested with a real robot.
2. Deploy with the match task:

   ```bash
   pixi run deploy-match -- --number 3 --wifi <FIELD_SSID> --wifi-psk <PASSWORD>
   ```

   Status: not tested with a real robot.

`deploy-match` runs `scripts/deploy.sh --force-gc --no-rerun`. In the copy of `deploy.yaml` that goes to the robot it
sets:

- `useGameController: true`
- `useRerun: false`
- `oraculum: "match"`, but only when the value was `"practice"`. `"off"` stays `"off"`, and the robot then sends no
  telemetry at all.

Your local `deploy.yaml` does not change.

3. Start Maximus and check the log line `DebugMessageSender: Sending debug data to <oraculumHost>:10006 (match mode, 1/s)`.
   Status: not tested with a real robot.

## The gateway match switch

The robot side (`oraculum: "match"`) stops the robot from listening. The gateway match switch stops the laptop from
sending. Use both in an official match.

- Turn it on with `match: true` in `/DATA/RoboCup/oraculum/config.yaml`, or with the environment variable
  `ORACULUM_MATCH=1`. The variable overrides the file: `ORACULUM_MATCH=0` turns the switch off.
- One guard (`ControlServer.blocked()` in `/DATA/RoboCup/oraculum/src/control_server.py`) stops every datagram that the
  gateway sends: joystick (`POST /control`), STOP, LIE DOWN, DAMP, Resume, Get up, Sit down (`POST /stop`), Go to
  (`POST /goto`) and camera requests (UDP 10008, `/DATA/RoboCup/oraculum/src/camera_hub.py`).
- `POST /control` (with `isManual: true`), `POST /stop`, `POST /goto` and `POST /gc` answer **HTTP 409** with
  "Match mode (oraculum match switch): the gateway sends nothing to the robots or the GameController (HSL rules,
  robot_players.tex L285-289 ...)".
- The simulated referee does not start. `ORACULUM_SIM_GC`, `ORACULUM_GC_TARGETS` and `ORACULUM_CONTROL_IP` are ignored,
  and the gateway prints a warning for each one that is set.
- The gateway still receives: telemetry on UDP 10006, camera frames on UDP 10009, and the GameController on UDP 3838
  (listen only). Recording, event marks, the TV program and the TV and director pages keep working.
- `GET /state` carries `"match": true`. Every page with a control bar (main view, IDE-style view, fleet, robot page)
  shows an amber chip **MATCH — no commands** and disables every command control: STOP ALL, the STOP, Resume, Get up,
  Sit down and LIE DOWN buttons, Go to, DAMP, MANUAL, the on-screen joystick, the bypass switch and the referee
  buttons. The tooltip names the rule.
- To leave match mode, restart the gateway without the switch. The open pages reload by themselves (tested in a
  browser with fake robots, 2026-10-23).

Independent of the switch: the gateway never sends a camera request to a robot that reports `sys.link = "telemetry"`
(a robot in `oraculum: "match"`). Such a robot streams no camera, and a request would only add traffic. The gateway
also never asks a read-only robot (no debug telemetry). For these robots the robot page tells why it has no camera
image.

## Network placement in an official match

Rule text: HSL rules at commit `06c44d4b`, `rules/robot_players.tex`.

| Line | Rule | What we do |
|---|---|---|
| [L285](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L285), [L287](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L287) | Robots act autonomously. No teleoperation, remote control, remote processing or "remote brain of any kind". | Robots run `oraculum: "match"` (no command port). The gateway runs with `match: true` (it sends nothing). |
| [L289](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L289) | Communication only among the robots, the referees and the GameController. | The laptop only receives. The robots' 1 packet per second of debug data is the exception of L373-374. |
| [L307](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L307), [L310](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L310) | One wireless access point per field. Each team gets a range of IP addresses for its robots **and** its computers. | The laptop takes an IP from our team range. |
| [L311](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L311) | The network configuration (IP addresses, channels, SSIDs, encryption) is announced at the competition site. | Ask the organisers on site. |
| [L314](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L314) | No other 2.4 GHz or 5 GHz radio close to the field, including phones and Bluetooth. | Laptop Wi-Fi and Bluetooth off. No phone, tablet or Android app near the field. |
| [L373](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L373), [L374](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L374) | Each robot may send debug data in one UDP packet to **one** team device on the **wired** network, at most `\UDPDebugPacketRate` = 1 packet per second (`common/variables.tex` line 53). | `oraculumHost` = the laptop's wired IP. The robot sends 1 unicast packet per second to UDP 10006 of that address. |

```
        organisers: field access point (L307) and GameController
              │ Wi-Fi                               │ wired field network
              ▼                                     ▼
  robots (team IP range, L310)              oraculum laptop
  oraculum: "match"                         wired IP from the team range (L310)
  no UDP 10007, no UDP 10008                Wi-Fi OFF, Bluetooth OFF (L314)
                                            gateway match: true (sends nothing)

  robot ──UDP 10006, 1 packet/s, unicast to oraculumHost (L373-374)──► laptop
  robot ◄──UDP 10000+team, team messages, broadcast (budget)──► robots
  GameController ──UDP 3838──► robots and laptop (the laptop only listens)
  robot ──status packets (L363)──► GameController
  laptop ──nothing──► robots, GameController

  near the field: no phones, tablets or the Android app (L314)
```

Steps:

1. Ask the organisers where the wired port of our team is, and which IP range we have (L310-311). The rules leave this
   open: they do not say where the wired network ends or who gives the cable.
2. Connect the laptop to the wired field network. Give it a fixed IP from the team range. Turn its Wi-Fi and Bluetooth
   off (L314).
3. Deploy the robots with `pixi run deploy-match` and `oraculumHost` = the laptop's wired IP (see below).
4. Start the gateway with the switch: `ORACULUM_MATCH=1 python3 run_oraculum.py`. Check the chip
   "MATCH — no commands" in the page header.
5. Keep phones, tablets and the Android companion app (`/DATA/RoboCup/robocup-hsl-companion`) away from the field
   during the match (L314). Read the pages on the laptop, or on a device that is not near the field.

**Debug packets and the message budget.** The message budget counts team messages only. This is an inference from the
rule text, not a sentence of the rules: the budget is part of the paragraph "Wireless Robot-To-Robot Communication"
([L317-356](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L317-L356)). It counts the messages on the team port (`10000 + team number`, [L328-329](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L328-L329)),
and the GameController monitors them ([L352](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L352)). Debug data is a separate paragraph
([L368-375](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L368-L375)) and goes to UDP 10006 of the laptop, not to the team port. An older draft of the rule,
commented out in the same file ([L334-336](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/robot_players.tex#L334-L336)), said "in addition to" the team-message limit.
Status: not confirmed by the organisers.

## What you see in oraculum during a match

- The field, fleet and TV pages work, with 1 update per second per robot.
- The robot page shows no camera image.
- With the gateway match switch on, every command control is disabled and the header shows "MATCH — no commands".
- Without the switch: **STOP, LIE DOWN, DAMP, Resume, Get up, Sit down and Go to are refused** for a robot in match
  mode. The robot reports `sys.link = "telemetry"`, so the gateway sends it nothing and answers HTTP 409 "This robot is
  in match mode". The page shows that text. MANUAL (`POST /control`) is not refused: the gateway sends the joystick
  datagrams, and the robot does not listen. Use the switch in a match. STOP ALL skips match-mode robots and still reaches robots in
  practice mode.
- Use the robot's own remote controller, or the referee.
- A robot can disappear from the view for a moment: see "1 packet per second and the 3.5 s timeout" in
  [Known Issues](Known-Issues).

## Team messages and the message budget

The robots of a team talk to each other with **team messages** on UDP `10000 + team number` (UDP 10019 for team 19).
The GameController gives each team a **message budget** of 12000 messages per game. It counts every packet on that
port in READY, SET and PLAYING. A team that uses more than its budget loses all its goals for the game
([game.tex, line 611](https://github.com/RoboCup-HumanoidSoccerLeague/HSL-Rules/blob/06c44d4b0ea2fd3cd4fdcc2a7cb907f6ace400dc/rules/game.tex#L611)).

- The referee pill in the main view shows the budget that the GameController announces.
- The budget does not reset at half time. Additional time adds 600 per minute; extra time adds 6000.
- The simulated referee of oraculum always announces 12000. It does not count down.
- The robot code of `mappazzone` stops all team messages when the budget is low. See [Known Issues](Known-Issues).
- **Team 6 conflict:** the oraculum telemetry port 10006 is also the team-message port of team 6. The GameController
  counts every packet that reaches it on that port, from any host. When our robots **broadcast** telemetry (an empty
  `oraculumHost` with Rerun mode other than `connect`), a GameController for team 6 on the same network counts our
  packets against team 6's budget. Match mode never broadcasts, so it avoids this on a switched network.
  This comes from the GameController code. It is not measured.
