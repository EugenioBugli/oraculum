# Screenshots to add

Take each screenshot with the gateway and fake robots running (`python3 tools/udp_sender.py` and
`ORACULUM_SIM_GC="19,2" python3 src/control_server.py`), unless the line says otherwise. Save it with the file name
below in this folder. Take them after the UI rework ends.

| File | Used in | What the screenshot must show |
|---|---|---|
| `field-2d.png` | Home, Pages | Main view (`/?mode=2d`) with all 7 robots, their "T19 R3" labels, the ball, some debug drawings and the referee pill in PLAYING. |
| `field-3d.png` | Pages | Main view in 3D with the "Circus (exact)" engine, robots with labels on the circus field. |
| `dashboard.png` | Pages | The IDE-style view (`/dashboard.html`) with its panels and the timeline. |
| `fleet.png` | Pages | Fleet tab of `/fleet.html` with all robot rows, one row STOPPED (after `oraculum_cli.py stop --ip 127.0.0.1`), the STOP ALL button and the control lock chip in the header. |
| `fleet-events.png` | Pages | Events tab of `/fleet.html` with game-state, goal, STOP and one manual mark event, and the filter buttons. |
| `fleet-recordings.png` | Pages | Recordings tab of `/fleet.html` with at least one recording and its Download link. |
| `robot.png` | Pages | `/robot.html?robot=1` with the fake camera image, the projected field lines, the "What this robot believes" panel and the closed "Danger" section. |
| `tv.png` | Pages | `/tv.html` in AUTO with the scoreboard (team names), the 2D field and a banner. |
| `director.png` | Pages | `/director.html` with AUTO/MANUAL, the view buttons, the robot choice, the banner field and the TV preview. |
| `architecture.png` | Architecture and Ports | A diagram of the data flow: GameController, robots, gateway and clients, with the ports 3838, 10006, 10007, 10008, 10009, 10000+team and 8080 on the arrows. |
