# Operator UI plan

Updated 2026-10-25. This plan covers routine practice and test operations from one Oraculum interface. The robot is currently disconnected; no deployment or motion command is part of this plan's implementation.

## Entry and workflow

Put **Operations** in the session menu beside **Real session**, **Simulated session**, **Real + ghosts**, and **Settings**. Keep the field and fleet views for monitoring and in-session controls; the Operations workspace handles connection, software, services, diagnostics, and logs. A simulated session opens the scenario wizard. The first hybrid slice is a browser display overlay: simulated ball and players never enter robot control.

1. **Connect / preflight:** choose one robot by identity, select Ethernet or a later network profile, show the laptop interface/address, SSH reachability, model/player number, installed commit, service state, telemetry age, control mode, and camera/debug ports. State the source and age of every result. A direct Ethernet path must work without Wi-Fi settings or internet.
2. **Prepare software:** select a known checkout/commit and practice or match profile, show a read-only diff of generated robot config and a build/deploy preview. Refuse a deploy when model, identity, address, disk, build, or profile checks fail. Stage an artifact with checksum and version metadata.
3. **Deploy:** one explicit per-robot action, progress stream, bounded timeout, and cancel before activation. Take a backup of the current binary and config, transfer over SSH, verify checksum, then activate through a dedicated adapter. Report the old and new versions and keep a one-click rollback. Never send credentials to the browser or persist them in a scenario file.
4. **Operate:** show service status and bounded start, stop, restart, rollback, and log actions. Explain that a service restart can release motor control. Show the observed robot state after an action, rather than equating transport success with physical completion.
5. **Diagnose:** collect a small, redacted bundle of service logs, joystick receiver presence, UDP telemetry, GameController state, version, and network routes. Offer copyable SSH commands for every action so the UI has an auditable CLI equivalent.

## Command inventory

| Group | UI action | Existing mechanism and constraint |
|---|---|---|
| Fleet health | refresh status, versions, telemetry, camera, GC, lock | Gateway `/state`, `/field`, `/events`, `/positions`, `/recordings`; SSH preflight adds service/device facts. |
| Recording | start/stop/list/download recording | Existing gateway recording routes and Fleet page. |
| Safety | STOP one/all, lie one/all, DAMP one | Existing gateway `/stop`; DAMP requires the supported robot, physical support, and the existing single-target confirmation. STOP ALL applies only to robots with recent debug telemetry and skips damped robots. |
| Practice control | Resume, Get up, Sit down, Go to/cancel, manual walk/turn | Existing `/stop`, `/goto`, `/control`, and CLI. Respect the control lock and READY/SET/PLAYING rule. Sit is currently unsupported by the installed T2 SDK despite a gateway action; display this as unavailable until robot-side support exists. A browser turn control requires the same bounded dead-man/timeout semantics as CLI `walk`; never infer completion from UDP send. |
| Robot mode | Prep/Walk/Manual, joystick receiver state | Distinguish manufacturer remote combos from Oraculum's UDP commands. Expose only mappings the installed firmware actually supports; show physical-button instructions where remote input cannot be issued over SSH. |
| Software | build, dry run, wired deploy, practice/match profile, version, rollback | The current `scripts/deploy.sh` requires `--wifi` and changes Wi-Fi. Implement a separate wired-only adapter or an explicit safe mode before enabling Ethernet deploy in the UI. Do not wrap arbitrary shell input. |
| Service | status, start, stop, restart, recent logs, boot enablement | Use fixed `systemctl`/journal operations behind a narrow server API with allowlisted host and service. Verify the actual service name from the target before exposing it. |
| Network | Ethernet address/routing/SSH; later Wi-Fi and internet sharing | Ethernet first. A later network wizard can preview Wi-Fi and laptop NAT changes, test reachability, and provide rollback. Never apply network changes as a side effect of a deploy preview. |
| Simulation | real session, simulated session wizard, real + ghosts, edit settings | Current UI overlay. A later simulator launcher must validate scene and field config, start an isolated process/session, report progress, and stop it cleanly. Physical robot reaction to ghosts needs a separately reviewed world-state bridge. |

## Backend contract and safeguards

- Create an `operations` backend separate from the browser and gateway command handlers. Use typed operations with allowlisted robot addresses, service names, artifact paths, and arguments; no general-purpose shell endpoint.
- Model each operation as `preflight → preview → execute → verify → result`, with a job ID, operator, robot identity, output, timestamps, and an idempotency key. Stream build/deploy/log progress and preserve a short audit history.
- Authenticate operators and separate read-only monitoring, practice commands, deployment, and host administration. The current gateway's optional access token is insufficient as a multi-operator authorization scheme. Keep the existing control lock for motion and enforce all command rules on the server.
- Require fresh telemetry or SSH evidence before a target is selected; label unknown state rather than assume ready. A lost browser session must not leave motion streaming. No UI command is enabled for a simulated ghost, a team-message-only robot, or an unsupported firmware feature.
- For service replacement and DAMP, require the physical setup state to be explicitly confirmed at execution time. Keep STOP visible everywhere it is supported, but state clearly when match mode or loss of robot telemetry means Oraculum cannot deliver it.

## Delivery order and acceptance

1. **Inventory and read-only Operations page:** connection, versions, service, joystick device, telemetry and logs. Validate against a disconnected robot and a reachable Ethernet robot; no accidental write or UDP control.
2. **Wired artifact path:** build/stage/checksum, dry-run/config diff, backup, transfer, activate, verify and rollback. Unit-test allowlists and failure rollback, then rehearse in simulation and with one supported robot on a stand. Do not reuse the Wi-Fi-mutating deploy path for this action.
3. **Command consolidation:** link existing control actions into the Operations page, fill the turn/dead-man gap, and show firmware capability plus actual reported latch/state. Test lock contention, referee blocking, ghost/read-only exclusion and loss of telemetry.
4. **Simulation job control:** wire the wizard's scene and field into an isolated simulator launcher; show real process state and stop controls. Add physical robot reaction to simulated objects only after a defined coordinate/time/authority contract and a dedicated safety test.
5. **Network profiles:** Wi-Fi and laptop internet sharing with explicit preview and rollback, after Ethernet workflow works end to end.

Acceptance for a typical session: an operator can identify one Ethernet robot, see what is running, deploy a pinned practice build with a verified rollback, confirm telemetry, send a supported practice command under the lock, see the robot's reported result, inspect logs, and restore the prior build without opening a terminal. An unsupported or disconnected robot produces a specific blocked reason and no side effect.
