# Troubleshooting

Each entry gives the symptom, the likely cause and the check. The checks come from the code. They are not tested
with a real robot.

## The gateway does not start: "Address already in use"

- Another gateway runs on this computer. Port 8080 is fixed, so only one gateway can run.
- Check: `ss -ltnup | grep -E ':(8080|10006|3838)\b'`. Stop the other process.
- A running `tools/udp_sender.py` also holds UDP 10007 and 10008. It does not block the gateway.

## The pages are empty: no robot

1. Check the robot log for `DebugMessageSender: Sending debug data to <laptop IP>:10006`.
   - "Disabled, no target" or a `192.168.10.x` address: `oraculumHost` in `deploy.yaml` is empty or wrong.
   - No `DebugMessageSender` line: the robot runs code without the oraculum settings (see the precondition in
     [Field Setup](Field-Setup)), or `oraculum: "off"` with `useRerun: false`.
   - "oraculum: match needs oraculumHost in deploy.yaml; telemetry off": set `oraculumHost`, deploy again.
2. Check that the laptop has the IP in `oraculumHost`: `ip -4 addr`.
3. Check that packets arrive: `sudo tcpdump -ni any udp port 10006`.
4. Check the firewall: UDP 10006 must come in.
5. Check that the robot and the laptop are on the same network and can reach each other: `ping 10.0.19.103`.

## A robot blinks in and out of the view

- In match mode the robot sends 1 packet per second, and the gateway drops a robot 3.5 s after its last packet.
  Three lost packets in a row remove the robot for a moment. See [Known Issues](Known-Issues).
- In practice mode: a weak Wi-Fi link. The fleet table shows the link rate and the age of the last packet.

## STOP or the joystick does nothing

- HTTP 409 "This robot is in match mode": the robot runs with `oraculum: match` and takes no command. Use its own
  remote controller, or deploy with `oraculum: practice` for a practice session.
- HTTP 409 "Match mode (oraculum match switch)", or the header chip "MATCH — no commands": the gateway runs with
  `ORACULUM_MATCH=1` or `match: true` in `config.yaml`, and sends nothing. Restart it without the switch for a practice
  session.
- The page says "sent", but the robot does not confirm. Look for STOPPED in the fleet row.
- HTTP 409 "No robot reached": no robot sends telemetry to this gateway. The gateway sends commands only to IPs that
  send telemetry.
- HTTP 423: another operator holds the control lock (MANUAL, Resume). Ask for it in the header.
- HTTP 403 (MANUAL, walk): the referee state is READY, SET or PLAYING.
- A firewall on the robot side or a network that blocks UDP 10007 between the laptop and the robots.

## The camera shows "waiting"

- The robot runs in match mode: no camera.
- The robot cannot reach the laptop on UDP 10009 (firewall).
- In the hosted sessions the camera is off (circus runs with `--no-images`).
- The fake robots send camera images only with `Pillow` installed.

## The referee pill is empty

- The GameController packets do not reach the laptop on UDP 3838. Check with `sudo tcpdump -ni any udp port 3838`.
- The gateway runs with `ORACULUM_SIM_GC`. It then ignores the real GameController. Restart it without the variable.
- The gateway shows a GameController state for 2 s after the last packet.

## Our robots are drawn on the wrong side

- Robots of the colour in `frames.mirror_team_color` (`config.yaml`, default `blue`) are mirrored into the shared field
  frame. If a team already sends field coordinates, set it to `""`.

## The 3D view shows boxes or a message

- The circus or MuJoCo files are missing. Run `tools/fetch_web_assets.sh` and `python3 tools/fetch_circus_scene.py`
  with an internet connection.
- The browser has no WebGL2. Use the 2D view.
- "Restoring the 3D view…": the browser lost the WebGL context. The page reloads the scene in 3–20 s.

## Every CLI command fails with 401

- The gateway runs with `ORACULUM_ACCESS_TOKEN`. Run the CLI with the same variable:
  `ORACULUM_ACCESS_TOKEN=<secret> python3 src/oraculum_cli.py status`.

## `status` stops with `KeyError: 'state'`

- No GameController packet arrived in the last 2 s (none runs, or it went silent for a moment). This is a bug of the
  CLI. Use the fleet page, or run the command again when the GameController sends.

## The fleet table marks the version

- The robot's commit is not the commit of the `spqrbooster2026` checkout next to the gateway (`../spqrbooster2026`).
  `+dirty` means the robot was deployed from a checkout with local changes. Deploy a clean `oraculum-tcm`
  (`d55b0946` or later, see [Field Setup](Field-Setup)).
