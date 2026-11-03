"""Wired binary/config transaction with remote rollback. No Wi-Fi side effects."""
import hashlib
import json
from pathlib import Path
import shlex
import tarfile

from wired_deploy_plan import plan


def identity_script(target, layout):
    # Read only the identity fields; never emit the active config or credentials.
    code = "import sys,yaml; d=yaml.safe_load(open(sys.argv[1])); assert d.get('robot')==sys.argv[2] and d.get('number')==int(sys.argv[3]), 'robot identity differs from configured target'"
    return "set -e\npython3 -c " + shlex.quote(code) + " " + shlex.quote(layout["config"] + "/deploy.yaml") + " " + shlex.quote(target["model"]) + " " + shlex.quote(str(target["number"])) + "\n"


def execute(manager, identifier, target, spec):
    layout = manager._layout(target["id"])
    binary, config = layout["binary"], layout["config"]
    base = str(Path(binary).parent)
    backup_id = spec.get("job", identifier)
    backup = base + "/.oraculum-backup-" + backup_id
    incoming = base + "/.oraculum-incoming-" + identifier
    quote = shlex.quote
    service = target["service"]
    services = layout.get("services", [service])
    stop_services = " ".join(quote(s) for s in reversed(services))
    start_services = "\n".join(f"sudo -n systemctl start {quote(s)}" for s in services)
    save_states = "\n".join(f"(systemctl is-active {quote(s)} || true) >{quote(backup + '/active-' + s)}" for s in services)
    restore_states = "\n".join(f'if test "$(cat {quote(backup + "/active-" + s)})" = active; then sudo -n systemctl start {quote(s)}; systemctl is-active --quiet {quote(s)}; fi' for s in services)
    # Paths come only from server configuration; verify the service really uses this binary.
    preflight = identity_script(target, layout) + f"""set -Eeuo pipefail
test -f {quote(binary)}; test -d {quote(config)}
test ! -L {quote(binary)}; test ! -L {quote(config)}
systemctl show {service} --property=ExecStart --value | grep -F -- {quote(binary)} >/dev/null
sudo -n -v
"""
    if spec["action"] == "rollback":
        manager._phase(identifier, "activating")
        current = incoming + '.previous'
        current_config = config + '.before-rollback-' + identifier
        current_states = "\n".join(f"(systemctl is-active {quote(s)} || true) >{quote(current + '-active-' + s)}" for s in services)
        recover_states = "\n".join(f'if test "$(cat {quote(current + "-active-" + s)})" = active; then sudo -n systemctl start {quote(s)}; systemctl is-active --quiet {quote(s)}; fi' for s in services)
        script = preflight + f"""
test -f {quote(backup + '/maximus_main')}; test -d {quote(backup + '/config')}
cp -a {quote(binary)} {quote(current)}
{current_states}
recover() {{
  trap - EXIT HUP INT TERM
  sudo -n systemctl stop {stop_services} || true
  cp -a {quote(current)} {quote(binary + '.restore')}
  mv -f {quote(binary + '.restore')} {quote(binary)}
  if test -d {quote(current_config)}; then
    test ! -e {quote(config)} || mv {quote(config)} {quote(config + '.failed-rollback-' + identifier)}
    mv {quote(current_config)} {quote(config)}
  fi
  {recover_states}
  echo ROLLBACK_FAILED_RESTORED >&2
  exit 1
}}
trap recover EXIT HUP INT TERM
sudo -n systemctl stop {stop_services}
cp -a {quote(backup + '/maximus_main')} {quote(binary + '.restore')}
mv -f {quote(binary + '.restore')} {quote(binary)}
cp -a {quote(backup + '/config')} {quote(config + '.restore-' + identifier)}
mv {quote(config)} {quote(config + '.before-rollback-' + identifier)}
mv {quote(config + '.restore-' + identifier)} {quote(config)}
{restore_states}
trap - EXIT HUP INT TERM
echo ROLLBACK_VERIFIED
"""
        output = manager._ssh(identifier, target, script)
        return {"backup": backup_id, "observed": output.strip(), "telemetry_verified": False}

    review = plan(manager.artifacts, spec["artifact"], target)
    folder = manager.artifacts / spec["artifact"]
    manifest = json.loads((folder / "manifest.json").read_text())
    required_kib = manifest["binary_size"] * 4 // 1024 + 100000
    preflight += f"test \"$(df -Pk {quote(base)} | awk 'NR==2 {{print $4}}')\" -ge {required_kib}\n"
    manager.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = manager.root / (identifier + ".tar")
    try:
        with tarfile.open(archive, "w") as tar:
            for name in ["maximus_main", "version.txt"] + ["config/" + n for n in manifest["config_files"]]:
                tar.add(folder / name, arcname=name, recursive=False)
        manager._phase(identifier, "transferring")
        manager._ssh(identifier, target, preflight + f"mkdir -m 700 {quote(incoming)}\n")
        manager.runner(identifier, ["scp", "-q", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                                    "-o", "ConnectTimeout=5", str(archive),
                                    target["user"] + "@" + target["ip"] + ":" + incoming + "/bundle.tar"], timeout=180)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        hashes = {"maximus_main": manifest["binary_sha256"], "version.txt": manifest["version_sha256"],
                  **{"config/" + k: v for k, v in manifest["config_files"].items()}}
        verify = f"cd {quote(incoming)}\necho '{digest}  bundle.tar' | sha256sum -c -\ntar xf bundle.tar\n"
        verify += "sha256sum -c <<'ORACULUM_HASHES'\n" + "\n".join(f"{v}  {k}" for k, v in hashes.items()) + "\nORACULUM_HASHES\n"
        verify += "ldd -r ./maximus_main >dependencies.txt 2>&1\n! grep -E 'not found|undefined symbol' dependencies.txt\n"
        manager._ssh(identifier, target, "set -Eeuo pipefail\n" + verify)
        manager._phase(identifier, "activating")
        script = preflight + f"""
test ! -e {quote(backup)}
mkdir -m 700 {quote(backup)}
cp -a {quote(binary)} {quote(backup + '/maximus_main')}
cp -a {quote(config)} {quote(backup + '/config')}
{save_states}
restore() {{
  trap - EXIT HUP INT TERM
  sudo -n systemctl stop {stop_services} || true
  cp -a {quote(backup + '/maximus_main')} {quote(binary + '.restore')}
  mv -f {quote(binary + '.restore')} {quote(binary)}
  if test -d {quote(config + '.previous-' + identifier)}; then
    test ! -e {quote(config)} || mv {quote(config)} {quote(config + '.failed-' + identifier)}
    mv {quote(config + '.previous-' + identifier)} {quote(config)}
  fi
  {restore_states}
  echo ACTIVATION_FAILED_RESTORED >&2
  exit 1
}}
trap restore EXIT HUP INT TERM
sudo -n systemctl stop {stop_services}
cp -a {quote(incoming + '/maximus_main')} {quote(binary + '.incoming')}
chmod 700 {quote(binary + '.incoming')}
mv -f {quote(binary + '.incoming')} {quote(binary)}
cp -a {quote(incoming + '/config')} {quote(config + '.incoming-' + identifier)}
cp {quote(incoming + '/version.txt')} {quote(config + '.incoming-' + identifier + '/version.txt')}
mv {quote(config)} {quote(config + '.previous-' + identifier)}
mv {quote(config + '.incoming-' + identifier)} {quote(config)}
{start_services}
sleep 3
systemctl is-active --quiet {service}
test "$(sha256sum {quote(binary)} | cut -d' ' -f1)" = {quote(manifest['binary_sha256'])}
trap - EXIT HUP INT TERM
echo ACTIVATION_VERIFIED
"""
        output = manager._ssh(identifier, target, script)
        return {"artifact": spec["artifact"], "source_commit": review["source_commit"],
                "backup": identifier, "observed": output.strip(), "telemetry_verified": False,
                "message": "Service and installed hash verified; check live telemetry and physical behavior separately"}
    finally:
        archive.unlink(missing_ok=True)
