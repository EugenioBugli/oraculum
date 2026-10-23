#!/bin/bash
# One oraculum session on a Hetzner VM, run by oraculum-sim.service (and by measure_rtf.sh): virtual display, noVNC view
# of the circus window, the gateway with the simulated referee, and circus in native Docker mode (one container per robot
# on CIRCUS_network). The access token is new at each boot (/run is a tmpfs) and stays the same across the hourly restarts.
set -u
SCENE=${SCENE:-/opt/session/5v5.yaml}
TOKEN_FILE=/run/oraculum/token
if [ ! -s "$TOKEN_FILE" ]; then
    mkdir -p /run/oraculum
    (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(16))' > "$TOKEN_FILE")
fi
ORACULUM_ACCESS_TOKEN=$(cat "$TOKEN_FILE")
export ORACULUM_ACCESS_TOKEN
trap 'kill $(jobs -p) 2>/dev/null' EXIT   # display, VNC and gateway end with circus

export DISPLAY=:1 XAUTHORITY=/root/.Xauthority
Xvfb :1 -screen 0 1600x900x24 -nolisten tcp &
sleep 1
x11vnc -storepasswd "$ORACULUM_ACCESS_TOKEN" /tmp/vncpass >/dev/null 2>&1
x11vnc -display :1 -forever -shared -rfbauth /tmp/vncpass -rfbport 5900 -localhost -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

# circus gives player P of team T the address 172.21.T.(P+10). The referee needs two teams: a lone team plays team 70.
read -r TEAMS IPS < <(python3 - "$SCENE" <<'PY'
import sys

import yaml

teams = yaml.safe_load(open(sys.argv[1]))["teams"].values()
numbers = [str(t["number"]) for t in teams] + ["70"]
print(",".join(numbers[:2]), ",".join(f"172.21.{t['number']}.{p['number'] + 10}" for t in teams for p in t["players"]))
PY
)
(cd /opt/oraculum && ORACULUM_SIM_GC=$TEAMS ORACULUM_GC_TARGETS=$IPS exec python3 -u src/control_server.py) &

# Hosted servers only (the robot image and the real robots keep it): booster-motion pins its real-time control thread
# to CPU 3 (hard-coded), so every robot's controller queues on one core. Unpin each new one; 5v5 RTF 0.22 -> 0.34
# (2026-10-21, CPX62). The binary pins once at start, so this holds until the robot restarts.
(while sleep 2; do
    for p in $(pgrep -x booster-motion); do
        grep -qE "^Cpus_allowed_list:\s+[0-9]+$" /proc/"$p"/task/*/status 2>/dev/null || continue   # no thread on one core
        taskset -a -p -c "0-$(($(nproc) - 1))" "$p" >/dev/null 2>&1
    done
done) &

cd /opt/circus
# Simulation config "rcap": circus's default with the match field (22 x 14 m, fieldRCAP.yaml of the robot framework, the
# field the robots localize on). Scenes pick it with simulation_config: rcap.
sed "s/^  field: .*/  field: fieldRCAP/" resources/config/simulation_configs/default.yaml > resources/config/simulation_configs/rcap.yaml
# Split session (split_peer.sh): CONNECT_MODE=socket and CIRCUS_DOCKER_SOCK_TEAM<n>=<socket> come from the caller
export FRAMEWORK_PATH=/workspace INFERENCE_BACKEND=onnx LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS=2
# --no-images: circus renders no camera frames (sim_fast uses the oracle). CIRCUS_IMAGES=1 (e.g. /etc/oraculum-sim.env)
# renders them for scenario sim_real (perception on the camera; costs CPU: llvmpipe renders every robot's camera)
./build/circus --scene "$SCENE" --framework /workspace/src/app/sim/docker_config.yaml --connect-mode "${CONNECT_MODE:-shm}" $([ -n "${CIRCUS_IMAGES:-}" ] || echo --no-images)
