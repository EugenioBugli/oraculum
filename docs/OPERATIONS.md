# Operations workspace

Open **Operations** from the Session menu on Field or Dashboard, or from Fleet. The page currently provides read-only diagnostics and an artifact preview. It does not deploy software, change services, command movement, or configure networking.

Targets are allowlisted in `config.yaml` under `operations.targets`. The initial target is robot 6 at its factory wired address `192.168.10.102/24`, SSH user `booster`, service `maximus`, model T1 as observed on 2026-10-25. Recheck identity and model before any deployment. Only one robot should be attached to that factory-address Ethernet segment at a time. Other targets need a confirmed `model: t1`, `t2`, or `k1` before staging.

The page always shows the gateway's IPv4 interfaces, whether one is on the configured robot subnet, and current robot telemetry with packet ages. **Run read-only SSH probe** checks TCP 22, then uses SSH batch mode with strict host-key checking and a five-second timeout. It reads service active state, installed version, `/dev/input/js*`, and the latest 30 service log lines. A disconnected robot, unknown host key, or absent SSH key produces an explicit failure; no password prompt or remote write is attempted.

The command map shows the currently supported paths for STOP, Resume, Lie down, DAMP, Get up, Go to, and manual movement. It links to the selected robot's controls only when that target has fresh command-capable debug telemetry. Sit remains listed as unavailable with the current T2 SDK. The map itself sends no command.

SSH diagnostics and artifact preview require the gateway to be started with `ORACULUM_ACCESS_TOKEN` and opened through its existing access link. The SSH probe is additionally disabled in match mode. The browser does not store a robot password. Do not put an access token in `config.yaml` or commit it.

**Preview artifact** reads the local robot checkout configured as `fleet.repo`. It reports the Git commit/dirty state, AArch64 binary architecture and SHA-256, and only the proposed `robot`, `oraculum`, `oraculumHost`, `useRerun`, `useGameController`, and `customMode` values. Wi-Fi credentials and unrelated config are excluded. A missing build, unknown target model, wrong architecture, dirty checkout, or missing gateway subnet address blocks staging. Preview performs no build or robot transfer.

Once those checks pass, a local terminal can pin the existing build without contacting the robot:

```bash
python3 tools/stage_artifact.py --target robot6 --profile practice
```

The staged binary, `deploy.yaml`, `version.txt`, and manifest live in ignored `artifacts/<commit>-<binary-hash>-<config-hash>/`, with restrictive permissions. Repeating the command verifies the existing copy; a mismatch fails. The staging tool refuses secret-looking fields in `deploy.yaml`. It is intentionally a CLI step until an authenticated host-operation API is designed. On 2026-10-26 the actual checkout correctly refuses staging: it is dirty, has no AArch64 binary, and the laptop has no address on the wired robot subnet.

Hardware acceptance remains open because the robot is disconnected. The next implementation stage is a bounded build job and a wired-only deploy adapter with backup, verification, and rollback. The existing deploy script requires Wi-Fi and must not serve as the wired adapter.
