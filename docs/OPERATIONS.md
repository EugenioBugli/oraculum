# Operations workspace

Open **Operations** from the Session menu on Field or Dashboard, or from Fleet. The page currently provides read-only diagnostics and an artifact preview. It does not deploy software, change services, command movement, or configure networking.

Targets are allowlisted in `config.yaml` under `operations.targets`. The initial target is robot 6 at its factory wired address `192.168.10.102/24`, SSH user `booster`, service `maximus`, model T1 as observed on 2026-10-25, player number 6, single-board layout, intended laptop address `192.168.10.236`, and isolated source checkout `/DATA/RoboCup/robot6-oraculum-build`. Recheck identity, model, board layout, and laptop address before any deployment. Only one robot should be attached to that factory-address Ethernet segment at a time. Other targets need a confirmed model, player number, and board layout before staging.

The page always shows the gateway's IPv4 interfaces, whether one is on the configured robot subnet, and current robot telemetry with packet ages. **Run read-only SSH probe** checks TCP 22, then uses SSH batch mode with strict host-key checking and a five-second timeout. It reads service active state, installed version, `/dev/input/js*`, and the latest 30 service log lines. A disconnected robot, unknown host key, or absent SSH key produces an explicit failure; no password prompt or remote write is attempted.

The command map shows the currently supported paths for STOP, Resume, Lie down, DAMP, Get up, Go to, and manual movement. It shows the selected robot's reported model, state, latch, version and packet age; the direct controls link appears only when fresh command-capable debug telemetry reports the configured model and the gateway is in practice mode. A blank latch may also mean old firmware did not report one. Sit remains listed as unavailable with the current T2 SDK. The map itself sends no command.

SSH diagnostics and artifact preview require the gateway to be started with `ORACULUM_ACCESS_TOKEN` and opened through its existing access link. The SSH probe is additionally disabled in match mode. The browser does not store a robot password. Do not put an access token in `config.yaml` or commit it.

**Preview artifact** reads the local robot checkout configured for the selected `operations.targets` entry (falling back to `fleet.repo`). It reports the Git commit/dirty state, AArch64 binary architecture and SHA-256, and only the proposed `robot`, `oraculum`, `oraculumHost`, `useRerun`, `useGameController`, and `customMode` values. Wi-Fi credentials and unrelated config are excluded. A missing build, unknown target model, wrong architecture, dirty checkout, or missing intended gateway subnet address blocks staging. Preview performs no build or robot transfer.

Once those checks pass, a local terminal can pin the existing build without contacting the robot:

```bash
python3 tools/stage_artifact.py --target robot6 --profile practice
```

The staged binary, complete `config/` tree, `version.txt`, and manifest live in ignored `artifacts/<commit>-<binary-hash>-<config-tree-hash>/`, with restrictive permissions. The bundle sets player number and board layout in `deploy.yaml` and `scenario: real` in `settings.yaml`. Repeating the command verifies the existing copy; a mismatch fails. The staging tool refuses secret-looking YAML fields and ignores only Pixi's untracked `.pixi-cache/` output in the source cleanliness check. It is intentionally a CLI step until an authenticated host-operation API is designed. Staging can use a configured intended laptop address while Ethernet is disconnected; activation later requires that address to be live on the interface.

On 2026-10-26 the existing 347,795,136-byte ARM binary from source commit `bc462d43` was staged locally with its full config as `bc462d4327f6-8e0f3dd4a8c3-144392754ea9` and passed the offline deploy review. The earlier incomplete bundle was removed. No build or robot transfer was performed. The binary hash pins the bytes; its source commit records the clean checkout, so build provenance still needs confirmation before hardware activation.

After staging, **Wired deployment review** lists the local artifacts and rechecks the binary and every config file hash, target identity, model, player number, board layout, profile, and intended gateway address before showing the proposed activation and rollback sequence. It has no deploy or service-action button. The UI also reports whether the intended gateway address is currently active on Ethernet. Fresh robot identity, SSH credentials, physical support, and the authenticated activation adapter remain prerequisites.

Hardware acceptance remains open because the robot is disconnected. The next implementation stage is a bounded build job and a wired-only deploy adapter with backup, verification, and rollback. The existing deploy script requires Wi-Fi and must not serve as the wired adapter.
