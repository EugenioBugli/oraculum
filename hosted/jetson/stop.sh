#!/bin/bash
# Stop everything of ours on the Jetson: measure/session scripts, circus, gateway, display, robot containers, network, shm.
# The [x] patterns keep pgrep from matching this script's own command line.
W=$HOME/oraculum-sim-arm
for pat in "measure_rt[f].sh" "$W/session.s[h]" "build/circu[s] --scene" "src/control_serve[r].py" "monitor_pla[y].py"; do
    pkill -u "$(id -u)" -f "$pat"
done
sleep 3
pkill -9 -u "$(id -u)" -f "build/circu[s] --scene"
docker rm -f oraculum-arm-display >/dev/null 2>&1
"$W/cleanup.sh"
