#!/bin/bash
# One oraculum session on the Jetson, everything local: virtual display (container), the gateway with the simulated
# referee (host python3), circus native on the host, one arm64 robot container per robot (circus starts them).
#   SCENE=~/oraculum-sim-arm/scenes/1v1.yaml ~/oraculum-sim-arm/session.sh
#   booster-motion: native aarch64 (T1 firmware 1.8.0.9) by default; BOOSTER_MOTION=box64 = the x86 0.0.11 under Box64
#   GPU=1: Maximus NNs on the Orin GPU. FRAMEWORK_CFG=<file in ~/oraculum-sim-arm> overrides both.
# View: ssh -L 8080:localhost:8080 -L 6080:localhost:6080 jetson-spqr, then http://localhost:8080/?token=<token>
# and http://localhost:6080/vnc.html (password = the token). Token: ~/oraculum-sim-arm/run/token.
set -u
W=$HOME/oraculum-sim-arm
SCENE=${SCENE:-$W/scenes/1v1.yaml}
DISP=${DISP:-:21}
mkdir -p "$W/run"
TOKEN_FILE=$W/run/token
[ -s "$TOKEN_FILE" ] || (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(16))' > "$TOKEN_FILE")
ORACULUM_ACCESS_TOKEN=$(cat "$TOKEN_FILE"); export ORACULUM_ACCESS_TOKEN
"$W/cleanup.sh" || exit 1
docker rm -f oraculum-arm-display >/dev/null 2>&1
stop() { kill $(jobs -p) 2>/dev/null
         # let a running clip recording (measure_rtf.sh) finish its file before the display goes away
         docker exec oraculum-arm-display pkill -INT ffmpeg >/dev/null 2>&1 && sleep 3
         docker rm -f oraculum-arm-display >/dev/null 2>&1; }
trap stop EXIT

# Display: Xvfb in a container on the host network (circus reaches it through the abstract X socket), VNC on
# localhost only, noVNC on 6080 (the VNC password is the token).
mkdir -p "$W/clips"   # measure_rtf.sh records the screen into it (ffmpeg in this container)
docker run -d --name oraculum-arm-display --network host -e TOKEN="$ORACULUM_ACCESS_TOKEN" -e DISP="$DISP" -v "$W/clips:/clips" \
    oraculum-arm-display bash -c 'Xvfb $DISP -screen 0 1600x900x24 -ac -nolisten tcp & sleep 1
        x11vnc -storepasswd "$TOKEN" /tmp/vncpass >/dev/null 2>&1
        x11vnc -display $DISP -forever -shared -rfbauth /tmp/vncpass -rfbport 5921 -localhost -quiet &
        exec websockify --web /usr/share/novnc 6080 localhost:5921' >/dev/null
sleep 2

# circus gives player P of team T the address 172.21.T.(P+10). The referee needs two teams: a lone team plays team 70.
read -r TEAMS IPS < <(python3 - "$SCENE" <<'PY'
import sys

import yaml

teams = yaml.safe_load(open(sys.argv[1]))["teams"].values()
numbers = [str(t["number"]) for t in teams] + ["70"]
print(",".join(numbers[:2]), ",".join(f"172.21.{t['number']}.{p['number'] + 10}" for t in teams for p in t["players"]))
PY
)
(cd "$W/oraculum" && ORACULUM_SIM_GC=$TEAMS ORACULUM_GC_TARGETS=$IPS exec python3 -u src/control_server.py) &

# booster-motion pins its real-time control thread to CPU 3 (hard-coded): with several robots they all queue on one
# core. Our user cannot taskset root processes, so unpin from inside each robot container (as on the hosted x86 servers).
(while sleep 2; do
    for c in $(docker ps -q --filter name=CIRCUS_ --filter ancestor=oraculum-arm-robot); do
        # ROBOT_CPUS=<n> (fall analysis): cap each robot container's CPU, to slow the lockstep down on purpose
        [ -n "${ROBOT_CPUS:-}" ] && docker update --cpus "$ROBOT_CPUS" "$c" >/dev/null 2>&1
        docker exec "$c" bash -c 'for p in $(pgrep -f /opt/booster/booster-motion); do
            grep -qE "^Cpus_allowed_list:\s+[0-9]+$" /proc/$p/task/*/status 2>/dev/null && taskset -a -p -c 0-$(($(nproc) - 1)) $p >/dev/null; done' 2>/dev/null
    done
done) &

# circus --framework file: docker_config[.box64][.gpu|_gpu].yaml
case "${BOOSTER_MOTION:-native}" in
    native) cfg=docker_config${GPU:+.gpu}.yaml ;;
    box64)  cfg=docker_config.box64${GPU:+_gpu}.yaml ;;
    *) echo "BOOSTER_MOTION must be native or box64" >&2; exit 1 ;;
esac
FRAMEWORK_CFG=${FRAMEWORK_CFG:-$cfg}
echo "framework config: $FRAMEWORK_CFG"
cd "$W/circus"
touch "$W/run/xauth"
export DISPLAY=$DISP XAUTHORITY=$W/run/xauth FRAMEWORK_PATH=$W/workspace INFERENCE_BACKEND=onnx \
    LIBGL_ALWAYS_SOFTWARE=1 LP_NUM_THREADS=2 QT_X11_NO_MITSHM=1
# CIRCUS_CPUS=<list> (fall analysis): pin circus to these cores, to slow the simulation down on purpose
${CIRCUS_CPUS:+taskset -c $CIRCUS_CPUS} ./build/circus --scene "$SCENE" --framework "$W/$FRAMEWORK_CFG" --connect-mode shm $([ -n "${CIRCUS_IMAGES:-}" ] || echo --no-images)
