# Authenticated operations

Operations has a read-only inventory plus an optional **Run a workflow** section. The Session menu opens the simulation wizard; its **Run an isolated simulation** section uses the same job API. No operation runs on page load. Controls appear for the operator's roles, with a preview, exact target confirmation, progress, history and an observed result. Service interruption also requires a fresh physical-support checkbox. Locking the page does not stop a job.

## Enable on a practice gateway

Keep the existing `operations.targets` inventory. Configure only verified installation paths and existing profiles; there are no default write destinations. Start the gateway with `ORACULUM_ACCESS_TOKEN` and a private `ORACULUM_OPERATORS` JSON environment variable:

```json
{"engineer":{"token":"<unique random secret of at least 24 characters>","roles":["software","deploy","service","network","simulation"],"targets":["robot6","gateway"]}}
```

Enter the operator token in the workflow form after opening the gateway access link. It stays in page memory and is cleared from the input. Do not commit tokens or place them in the URL. Use a trusted local interface or an HTTPS reverse proxy: operator headers are credentials. Match mode refuses this API. Operators see only their own jobs; authorization is enforced by the server, independently of the motion control lock.

The following is a configuration **template**, not robot 6's verified installation:

```yaml
operations:
  # Keep targets from the existing inventory; this extends that mapping.
  build_argv: [pixi, run, compile-aarch64, --skip-gcdo-update]
  deployments:
    robot6:
      binary: /home/booster/verified-install/bin/maximus_main
      config: /home/booster/verified-install/config
      services: [maximus-start, maximus] # start in this order, stop in reverse
  network_profiles:
    - id: robot-lab
      label: Robot lab Wi-Fi
      target: robot6
      interface: wlan0
      uuid: 00000000-0000-0000-0000-000000000001 # replace with an existing UUID
    - id: laptop-sharing
      label: Laptop Ethernet sharing
      target: gateway
      interface: enxEXAMPLE
      uuid: 00000000-0000-0000-0000-000000000002 # replace with an existing UUID
  simulator:
    image: registry.example/simulator@sha256:<full-image-digest>
    max_seconds: 1800
```

The gateway needs its configured build tool on PATH. Robot adapters require batch SSH key authentication, a previously verified known-host entry, Bash, Python 3 with PyYAML, `sha256sum`, `ldd`, systemd, and noninteractive sudo rights for the configured actions. Deployment paths must be under `/home`, and the primary service's ExecStart must refer to the configured binary. Service operations verify the current config's robot model/player identity before acting. An installation needing extra runtime libraries/models must already provide them; this adapter does not install packages or change library paths.

## Workflow behavior

| Role | Operations | Verified result |
|---|---|---|
| `software` | Build, stage practice/match artifact | Pinned clean checkout; build exit status; immutable binary/config hashes |
| `deploy` | Ethernet deploy, rollback | Installed hashes, dependency resolution and service state; exact binary/config backups |
| `service` | Start, stop, restart primary service | Observed systemd state, after identity verification |
| `network` | Apply an existing profile, restore its previous profile | Interface UUID/address and management reachability |
| `simulation` | Launch/stop a configured isolated image | Container process state/exit status and cleanup |

Build/stage previews pin the clean source commit. Staging supports both legacy `build/aarch64` and current `build/aarch64-<model>` outputs and config layouts. Wi-Fi credentials are excluded; other secret-looking YAML is rejected. The source commit records the checkout, not a cryptographic attestation that the binary was built from it.

Deploy revalidates the artifact and Ethernet address, checks remote identity/paths/free space, transfers a tar archive, verifies every hash and resolves ELF dependencies **before stopping services**. It retains the previous binary/config and original service states. Failed activation restores those; an explicit rollback also restores the pre-rollback installation if the older version fails. Backups remain on the robot until deliberately cleaned up. Activation cannot be cancelled halfway through. An SSH/process timeout can leave the result unknown; inspect the robot rather than assuming it stopped or retrying blindly. Systemd success does not prove telemetry, perception, gait or physical posture.

Network changes select existing, server-allowlisted NetworkManager UUIDs, not browser-supplied commands or passwords. Create/verify those profiles separately using the [connection guide](wiki/Field-Setup.md). Robot and laptop profiles are separate operations. Ethernet plus Wi-Fi internet, or laptop internet sharing, depends on those profiles' routing/DHCP settings; the job does not infer internet access. A systemd recovery timer is armed before activation and restores the prior connection after 90 seconds (or disconnects a previously unused interface). Robot changes require a second SSH round trip before disarming it. Laptop changes require **Keep this network connection** within 45 seconds after activation; a closed/disconnected browser leaves recovery armed. No networking was changed during offline verification.

Only one job runs at a time. Previews expire after two minutes; requests have idempotency keys. Jobs use bounded output and timeouts. Build/transfer/simulation can be cancelled; service/deploy activation cannot. STOP remains available during maintenance, while movement/resume toward that robot is refused. Audit records are private files under `.operation-jobs/` beside the artifact directory. After a gateway restart, unfinished jobs are marked interrupted/unknown rather than successful; check for surviving remote work or simulator containers before retrying. There is no automatic backup/audit retention deletion.

## Simulator image contract and remaining acceptance

This is a launcher adapter, not a bundled production simulator image. The pinned image entrypoint receives three arguments: `/scenario/scene.yaml`, `/scenario/field.yaml`, `/scenario/simulation.yaml`. It must load those resources into its Circus/Maximus stack and keep the foreground process alive. Real-robot slots are excluded; only simulated slots become scene players. The current launcher requires the ball at field centre. The container has no network, no extra capabilities, a read-only scenario mount, and CPU/memory/process/time limits. This deliberately cannot communicate with a physical robot. It reports process state only; live simulator telemetry/render streaming needs a separately qualified bridge.

The default config does not enable a simulator image or robot deployment paths. A production image and its scenario-loading behavior still need end-to-end acceptance. Browser ghost preview is immediately available and remains distinct from physics simulation. Feeding a simulated ball/opponents into a real robot is a separate, unimplemented coordinate/time/control contract.

## Verification

The tests use loopback HTTP, fixture subprocess adapters, and a temporary robot filesystem; they never send commands to a robot or change the host network:

```bash
python3 tools/test_operation_jobs.py
python3 tools/test_wired_transaction.py
python3 tools/test_operations_browser.py /tmp/oraculum-browser
python3 tools/test_workspace_browser.py /tmp/oraculum-browser
python3 tools/test_manual_browser.py /tmp/oraculum-browser
```

The browser suite exercises the actual authenticated HTTP routes and UI. The transaction suite executes generated shell scripts with fake sudo/systemctl/ldd and verifies exact restoration on failed activation and failed rollback. Actual SSH permissions, NetworkManager recovery, production image behavior and supported-robot motion remain deployment acceptance tests.
