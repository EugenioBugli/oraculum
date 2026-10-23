#!/bin/bash
# Reproduce the Jetson build of the hosted simulation from this laptop (the fastest known chain, JETSON.md).
#   hosted/jetson/build_all.sh            # NATIVE=0 skips the native booster-motion (the default; firmware 3.9 GB)
# 1. copies these scripts to jetson-spqr:~/oraculum-sim-arm (small),
# 2. streams the private sources from the x86 server straight to the Jetson (laptop not in the data path; needs this
#    laptop's ssh agent: ssh -A to the server, ProxyCommand through the droplet),
# 3. starts build_jetson.sh on the Jetson, detached, and follows its log (cold about 8 min, steps in parallel).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
J=${J:-jetson-spqr}
SERVER=${SERVER:-root@49.12.252.138}       # read-only use: tar of /workspace and /opt/oraculum
JUMP=${JUMP:-root@142.93.104.36}           # orchestrator droplet (lab VPN)
JHOST=${JHOST:-jetsonspqr@192.168.0.152}

ssh "$J" 'mkdir -p ~/oraculum-sim-arm/scenes'
scp -q "$HERE"/*.sh "$HERE"/*.py "$HERE"/*.yaml "$HERE"/*.conf "$HERE"/Dockerfile.* "$HERE"/*.patch \
    "$HERE/../vm/monitor_play.py" "$J:oraculum-sim-arm/"
scp -q "$HERE"/scenes/*.yaml "$J:oraculum-sim-arm/scenes/"
scp -q "$HERE"/booster-native/config_sim_circus.lua "$J:oraculum-sim-arm/"   # native booster-motion config

# Private sources: robot framework tree (without build/ and .pixi/, 464 MB, ~30 s) and the gateway (89 MB, ~6 s)
ssh -A "$SERVER" "O='-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/tmp/kh_jetson'
    P=\"ssh \$O -W %h:%p $JUMP\"
    tar -C /workspace -cz --exclude=./build --exclude=./.pixi . |
        ssh \$O -o ProxyCommand=\"\$P\" $JHOST 'mkdir -p ~/oraculum-sim-arm/workspace && tar -xz -C ~/oraculum-sim-arm/workspace'
    tar -C /opt -cz --exclude=oraculum/recordings --exclude=__pycache__ oraculum |
        ssh \$O -o ProxyCommand=\"\$P\" $JHOST 'tar -xz -C ~/oraculum-sim-arm'"

# Detached on the Jetson (the ssh path through the jump host drops now and then), then follow its log
ssh "$J" "cd ~/oraculum-sim-arm && mkdir -p logs && (NATIVE=${NATIVE:-1} setsid nohup bash build_jetson.sh > logs/build_jetson.log 2>&1 < /dev/null &)"
echo "building on the Jetson; log: $J:oraculum-sim-arm/logs/build_jetson.log"
until ssh "$J" 'grep -qE "real-time factor|FAILED|failed" ~/oraculum-sim-arm/logs/build_jetson.log' 2>/dev/null; do sleep 15; done
ssh "$J" 'cat ~/oraculum-sim-arm/logs/build_jetson.log'
