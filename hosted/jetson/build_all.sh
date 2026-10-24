#!/bin/bash
# Reproduce the Jetson build of the hosted simulation from this laptop (the fastest known chain, JETSON.md).
#   hosted/jetson/build_all.sh            # NATIVE=0 skips the native booster-motion (firmware 3.9 GB)
#   BUILD_TYPE=Debug hosted/jetson/build_all.sh   # Maximus -O0 in build/arm (default Release in build/arm-release)
# 1. copies these scripts to jetson-spqr:~/oraculum-sim-arm (small),
# 2. syncs the sources from this laptop: the robot tree SRC (default /home/xps/work/spqr-merge, without .git, .pixi,
#    build), simbridge ce708bfa (its submodule is empty in SRC) and the gateway (git HEAD of this oraculum clone),
# 3. starts build_jetson.sh on the Jetson, detached, and follows its log (cold about 8 min, steps in parallel).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
J=${J:-jetson-spqr}
SRC=${SRC:-/home/xps/work/spqr-merge}
SIMBRIDGE=${SIMBRIDGE:-/DATA/RoboCup/spqrbooster2026/external/simbridge}   # ce708bfa; build_jetson.sh adds 625336d2
ORACULUM=$(cd "$HERE/../.." && pwd)

ssh "$J" 'mkdir -p ~/oraculum-sim-arm/scenes'
scp -q "$HERE"/*.sh "$HERE"/*.py "$HERE"/*.yaml "$HERE"/*.conf "$HERE"/Dockerfile.* "$HERE"/*.patch \
    "$HERE/../vm/monitor_play.py" "$J:oraculum-sim-arm/"
scp -q "$HERE"/scenes/*.yaml "$J:oraculum-sim-arm/scenes/"
scp -q "$HERE"/booster-native/config_sim_circus.lua "$J:oraculum-sim-arm/"   # native booster-motion config

# Sources. No --delete: the Jetson keeps simbridge, models/ and the git-ignored gateway assets it already has; the
# robot patches overwritten here are applied again by build_jetson.sh. (The x86 server copy is gone, 2026-10-24.)
ssh "$J" 'mkdir -p ~/oraculum-sim-arm/workspace/external/simbridge ~/oraculum-sim-arm/oraculum'
rsync -a --exclude=.pixi --exclude=/build --exclude=.git "$SRC/" "$J:oraculum-sim-arm/workspace/"
rsync -a --exclude=.git "$SIMBRIDGE/" "$J:oraculum-sim-arm/workspace/external/simbridge/"
# /DATA is NTFS: git's symlinks there are "IntxLNK" stub files (libfmt.so.8, libSDL2-2.0.so.0; simbridge then fails
# with "file too short"). Make them real links on the Jetson, with the targets git stores.
git -C "$SIMBRIDGE" ls-files -s | awk '$1 == 120000 {print $2, $4}' | while read -r sha path; do
    printf 'ln -sfn %q %q\n' "$(git -C "$SIMBRIDGE" cat-file -p "$sha")" "oraculum-sim-arm/workspace/external/simbridge/$path"
done | ssh "$J" bash
git -C "$ORACULUM" archive HEAD src config fields config.yaml | ssh "$J" 'tar -x -C ~/oraculum-sim-arm/oraculum'

# Detached on the Jetson (the ssh path through the jump host drops now and then), then follow its log
ssh "$J" "cd ~/oraculum-sim-arm && mkdir -p logs && (NATIVE=${NATIVE:-1} BUILD_TYPE=${BUILD_TYPE:-Release} setsid nohup bash build_jetson.sh > logs/build_jetson.log 2>&1 < /dev/null &)"
echo "building on the Jetson; log: $J:oraculum-sim-arm/logs/build_jetson.log"
until ssh "$J" 'grep -qE "real-time factor|FAILED|failed" ~/oraculum-sim-arm/logs/build_jetson.log' 2>/dev/null; do sleep 15; done
ssh "$J" 'cat ~/oraculum-sim-arm/logs/build_jetson.log; ! grep -qE "FAILED|failed" ~/oraculum-sim-arm/logs/build_jetson.log'
# A FAILED step returns here at once while the other steps still run on the Jetson: wait for build_jetson.sh to end
# (ssh jetson-spqr 'pgrep -f "[b]uild_jetson.sh"' prints nothing; the brackets keep pgrep from matching its own
# ssh command line) before running this script again.
