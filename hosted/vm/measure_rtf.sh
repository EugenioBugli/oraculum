#!/bin/bash
# Real-time factor of the simulation on this VM. circus stops after SIM_S simulated seconds; RTF = SIM_S / wall seconds
# from "Starting simulation!" to the exit. 1.0 = real time; below 1 the robots move in slow motion.
# The referee goes to PLAYING, so the robots walk. Run it outside systemd (Restart=always would restart circus):
#   systemctl stop oraculum-sim; SCENE=/opt/session/5v5.yaml SIM_S=120 /opt/session/measure_rtf.sh
set -euo pipefail
SCENE=${SCENE:-/opt/session/5v5.yaml}
SIM_S=${SIM_S:-120}
cfg=/workspace/src/app/sim/simulation_configs
sed "s/^  max_simulation_time: .*/  max_simulation_time: $SIM_S/" "$cfg/default.yaml" > "$cfg/rtf.yaml"
sed 's/^simulation_config: .*/simulation_config: rtf/' "$SCENE" > /tmp/rtf_scene.yaml
/opt/session/cleanup.sh
log=/tmp/rtf.log
SCENE=/tmp/rtf_scene.yaml /opt/session/vm_session.sh > "$log" 2>&1 &
pid=$!
until grep -q "Starting simulation!" "$log"; do
    kill -0 "$pid" 2>/dev/null || { echo "circus stopped before the simulation started:" >&2; tail -20 "$log" >&2; exit 1; }
    sleep 0.5
done
t0=$(date +%s.%N)
tok=$(cat /run/oraculum/token)
for s in ready set playing; do
    curl -s -X POST "http://127.0.0.1:8080/gc?token=$tok" -H 'Content-Type: application/json' -d "{\"state\":\"$s\"}" >/dev/null
    # split session: the referee of the other host (PEER_GC_URL=http://<private ip>:8080/gc?token=<its token>)
    [ -n "${PEER_GC_URL:-}" ] && curl -s -X POST "$PEER_GC_URL" -H 'Content-Type: application/json' -d "{\"state\":\"$s\"}" >/dev/null
    sleep 2
done
sleep 20
kill -0 "$pid" 2>/dev/null && top -b -n 1 -o %CPU | head -22 > /tmp/rtf_top.txt   # CPU under load
wait "$pid" || true
t1=$(date +%s.%N)
python3 -c "w = $t1 - $t0; print(f'simulated $SIM_S s in {w:.1f} s of wall time: real-time factor {$SIM_S / w:.2f}')"
cat /tmp/rtf_top.txt 2>/dev/null
grep -c "Timeout, resending state" "$log" | sed 's/^/circus command timeouts: /'
/opt/session/cleanup.sh
