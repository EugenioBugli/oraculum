"""Activate existing NetworkManager profiles with independent timed recovery."""
import shlex
from pathlib import Path
import time


def execute(manager, identifier, target, spec):
    profile = next((p for p in manager.config.get("network_profiles", []) if p["id"] == spec.get("profile")
                    and p["target"] == target["id"]), None)
    backup_id = spec.get("job", identifier)
    home = str(Path.home()) if target["id"] == "gateway" else "/home/" + target["user"]
    record_dir = home + "/.local/state/oraculum-network"
    record = record_dir + "/" + backup_id
    q = shlex.quote
    manager._phase(identifier, "activating")
    if spec["action"] == "network-rollback":
        script = f"""set -e
previous=$(cat {q(record)})
if test "$previous" = NONE; then
  interface=$(cat {q(record + '.interface')})
  sudo -n nmcli device disconnect "$interface"
else
  sudo -n nmcli connection up uuid "$previous"
  nmcli -t -f UUID connection show --active | grep -Fx -- "$previous"
fi
"""
    else:
        interface, connection = profile["interface"], profile["uuid"]
        unit = "oraculum-net-" + identifier
        script = f"""set -Eeuo pipefail
mkdir -p -m 700 {q(record_dir)}
test ! -e {q(record)}
test "$(nmcli -g connection.interface-name connection show uuid {q(connection)})" = {q(interface)}
previous=$(nmcli -g GENERAL.CON-UUID device show {q(interface)})
if ! [[ "$previous" =~ ^[0-9a-fA-F-]{{36}}$ ]]; then previous=NONE; fi
umask 077
printf '%s\n' "$previous" > {q(record)}
printf '%s\n' {q(interface)} > {q(record + '.interface')}
if test "$previous" = NONE; then
  sudo -n systemd-run --unit={unit} --on-active=90s -- /usr/bin/nmcli device disconnect {q(interface)}
else
  sudo -n systemd-run --unit={unit} --on-active=90s -- /usr/bin/nmcli connection up uuid "$previous"
fi
sudo -n nmcli --wait 30 connection up uuid {q(connection)}
test "$(nmcli -g GENERAL.CON-UUID device show {q(interface)})" = {q(connection)}
test -n "$(nmcli -g IP4.ADDRESS device show {q(interface)})"
echo NETWORK_PROFILE_VERIFIED
"""
    output = manager._ssh(identifier, target, script)
    if profile:
        if target["id"] == "gateway":
            manager._phase(identifier, "awaiting network confirmation")
            deadline = time.monotonic() + 45
            while not manager.approvals[identifier].wait(.1):
                if manager.cancelled[identifier].is_set() or time.monotonic() > deadline:
                    # The recovery unit is independent of the gateway and also fires if the process dies.
                    raise ValueError("Network change not confirmed; the 90-second recovery timer remains armed")
        # A second SSH round trip verifies management connectivity after activation.
        manager._ssh(identifier, target, "set -e\nsudo -n systemctl stop oraculum-net-" + identifier + ".timer\necho RECOVERY_TIMER_CANCELLED\n")
    return {"observed": output.strip(), "backup": backup_id,
            "message": "Profile/interface and management connectivity verified; internet access is not inferred"}
