#!/bin/bash
# Real-time factor on the Jetson (same logic as hosted/vm/measure_rtf.sh): circus stops after SIM_S simulated seconds;
# RTF = SIM_S / wall seconds from "Starting simulation!" to the exit. The referee goes to PLAYING, so the robots walk;
# monitor_play.py logs motion and falls; top shows the CPU per process under load.
#   SCENE=~/oraculum-sim-arm/scenes/1v0.yaml SIM_S=60 ~/oraculum-sim-arm/measure_rtf.sh
#   env: BOOSTER_MOTION=box64 (default native), GPU=1, FRAMEWORK_CFG=<file>, SCENARIO=sim_real + CIRCUS_IMAGES=1,
#        MON_EVERY=<s>, RUN_NAME=<name>
set -euo pipefail
W=$HOME/oraculum-sim-arm
SCENE=${SCENE:-$W/scenes/1v1.yaml}
SIM_S=${SIM_S:-60}
mkdir -p "$W/run" "$W/logs"
cfg=$W/workspace/src/app/sim/simulation_configs
sed "s/^  max_simulation_time: .*/  max_simulation_time: $SIM_S/" "$cfg/default.yaml" > "$cfg/rtf.yaml"
sed 's/^simulation_config: .*/simulation_config: rtf/' "$SCENE" > "$W/run/rtf_scene.yaml"
log=$W/logs/rtf.log
rm -rf "$W/logs/robots"   # robot logs of this run only
rm -rf "$W/logs/robots"   # robot logs of this run only
# SCENARIO=sim_real: perception on the camera (set CIRCUS_IMAGES=1 too); settings.yaml goes back to sim_fast at the end
settings=$W/workspace/src/app/config/settings.yaml
if [ -n "${SCENARIO:-}" ]; then
    sed -i -E "s/^scenario: \"[a-z_]+\"/scenario: \"$SCENARIO\"/" "$settings"
    trap 'sed -i -E "s/^scenario: \"[a-z_]+\"/scenario: \"sim_fast\"/" "$settings"' EXIT
fi
SCENE=$W/run/rtf_scene.yaml "$W/session.sh" > "$log" 2>&1 &
pid=$!
until grep -q "Starting simulation!" "$log"; do
    kill -0 "$pid" 2>/dev/null || { echo "circus stopped before the simulation started:" >&2; tail -20 "$log" >&2; exit 1; }
    sleep 0.5
done
t0=$(date +%s.%N)
# Clip of every run: the circus window (virtual screen :21) at wall speed, 10 fps, 960x540. session.sh stops ffmpeg
# with SIGINT before it removes the display; the fragmented MP4 also survives a hard stop.
clip=${RUN_NAME:-rtf}_$(date +%Y%m%d_%H%M%S)
docker exec -d -u "$(id -u):$(id -g)" oraculum-arm-display ffmpeg -loglevel error -f x11grab -framerate 10 \
    -video_size 1600x900 -i "${DISP:-:21}" -vf scale=960:540 -c:v libx264 -preset veryfast -tune zerolatency -g 10 -crf 30 \
    -pix_fmt yuv420p -flush_packets 1 -movflags +frag_keyframe+empty_moov "/clips/${clip}_wall.mp4"
tok=$(cat "$W/run/token")
until curl -sf "http://127.0.0.1:8080/state?token=$tok" >/dev/null; do sleep 0.5; done
for s in ready set playing; do
    curl -s -X POST "http://127.0.0.1:8080/gc?token=$tok" -H 'Content-Type: application/json' -d "{\"state\":\"$s\"}" >/dev/null
    sleep 2
done
ORACULUM_TOKEN_FILE=$W/run/token timeout $((SIM_S * 3)) python3 -u "$W/monitor_play.py" --seconds $((SIM_S * 3)) --every ${MON_EVERY:-10} \
    > "$W/logs/monitor.log" 2>&1 &
# circus removes the robot containers when it exits: keep the first 3 MB (.head) and the last 2 MB of each robot log
(while kill -0 "$pid" 2>/dev/null; do
    for n in $(docker ps --format '{{.Names}}' --filter name=CIRCUS_ --filter ancestor=oraculum-arm-robot); do
        mkdir -p "$W/logs/robots/$n"
        for f in booster-motion simbridge maximus; do for x in log err; do
            docker exec "$n" tail -c 2000000 /var/log/$f.$x > "$W/logs/robots/$n/$f.$x.tmp" 2>/dev/null \
                && mv "$W/logs/robots/$n/$f.$x.tmp" "$W/logs/robots/$n/$f.$x"
            [ -s "$W/logs/robots/$n/$f.$x.head" ] && [ "$(stat -c %s "$W/logs/robots/$n/$f.$x.head")" -ge 3000000 ] \
                || docker exec "$n" head -c 3000000 /var/log/$f.$x > "$W/logs/robots/$n/$f.$x.head" 2>/dev/null   # the start
        done; done
    done
    sleep 5
done) &
sleep 20
kill -0 "$pid" 2>/dev/null && top -b -n 2 -d 3 -o %CPU -w 200 | awk '/^top -/{n++} n==2' | head -30 > "$W/logs/rtf_top.txt" || true   # head closes the pipe early: not an error
wait "$pid" || true
t1=$(date +%s.%N)
kill %2 %3 2>/dev/null || true
python3 -c "w = $t1 - $t0; print(f'simulated $SIM_S s in {w:.1f} s of wall time: real-time factor {$SIM_S / w:.2f}')"
# Real-speed copy: the wall clip sped up by 1/RTF (the simulation ran slower than real time)
rtf_x=$(python3 -c "print(f'{$SIM_S / ($t1 - $t0):.4f}')")
docker run --rm --network host -u "$(id -u):$(id -g)" -v "$W/clips:/clips" --entrypoint "" oraculum-arm-display \
    ffmpeg -loglevel error -y -i "/clips/${clip}_wall.mp4" -vf "setpts=${rtf_x}*PTS" -r 25 -c:v libx264 -preset veryfast \
    -crf 30 -an "/clips/${clip}_realspeed.mp4" && echo "clips: $W/clips/${clip}_wall.mp4 ${clip}_realspeed.mp4" || echo "clip: FAILED"
cat "$W/logs/rtf_top.txt" 2>/dev/null
grep -c "Timeout, resending state" "$log" | sed 's/^/circus command timeouts: /' || true
sed '/^Traceback/,$d' "$W/logs/monitor.log"   # the monitor ends with a traceback when the gateway stops
# RUN_NAME=<name>: keep the robot logs and monitor of this run in logs/falls/<name>/ and count the falls
if [ -n "${RUN_NAME:-}" ]; then
    d=$W/logs/falls/$RUN_NAME; mkdir -p "$d"
    cp -r "$W"/logs/robots/. "$d/" 2>/dev/null; cp "$W/logs/monitor.log" "$W/logs/rtf_top.txt" "$d/" 2>/dev/null
    rtf=$(python3 -c "print(f'{$SIM_S / ($t1 - $t0):.2f}')")
    first=$(grep -m1 FALLEN "$W/logs/monitor.log" | awk '{print $1}' || true)
    n=$(cat "$d"/*/maximus.err 2>/dev/null | grep -c "IS_STANDING -> IS_FALLING" || true)
    echo "$RUN_NAME rtf=$rtf falls=$n first_FALLEN_wall_s=${first:-none} scene=$(basename "$SCENE") scenario=${SCENARIO:-sim_fast} ball=${CIRCUS_BALL_POS:-default} circus_cpus=${CIRCUS_CPUS:-all}" \
        | tee -a "$W/logs/falls/summary.txt"
fi
"$W/cleanup.sh"
