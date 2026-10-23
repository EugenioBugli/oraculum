# Match Mode and Rules

Result first: for an official match, deploy with `pixi run deploy-match`. It turns `oraculum: "practice"` into
`oraculum: "match"`. In match mode each robot sends **1 telemetry packet per second to `oraculumHost` only**, and it
accepts **no** command from oraculum: no joystick, no STOP, no LIE DOWN, no DAMP, no camera.

**Status: not tested with a real robot (not run in simulation either).** The code is new on 2026-10-21.
The `deploy.yaml` patch of `deploy-match` was checked with `yq` on a sample file.

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

## What you see in oraculum during a match

- The field, fleet and TV pages work, with 1 update per second per robot.
- The robot page shows no camera image.
- **STOP, LIE DOWN, DAMP, Resume and MANUAL are refused.** The robot reports `sys.link = "telemetry"`, so the gateway
  sends it nothing and answers HTTP 409 "This robot is in match mode". The page shows that text.
  STOP ALL skips match-mode robots and still reaches robots in practice mode.
  Use the robot's own remote controller, or the referee.
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
