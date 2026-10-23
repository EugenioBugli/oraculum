#!/bin/bash
# Copy what a Hetzner session VM builds from, straight from this laptop's working trees to the VM, then run
# /opt/session/provision.sh there. Nothing is staged locally: /DATA and / are nearly full.
#   hosted/vm/push.sh root@<ip>
# CIRCUS_REF and SIMBRIDGE_REF must be a matching pair: circus writes, and simbridge reads, the same shared-memory
# layout, which changed with the T2 integration. Fallback: the pair spqrbooster2026 main pins (2026-10-19), 4 ms timestep:
#   CIRCUS_REF=ae484b3d SIMBRIDGE_REF=11a4b707 hosted/vm/push.sh root@<ip>
set -euo pipefail
VM=${1:?usage: hosted/vm/push.sh root@<ip>}
CIRCUS_REF=${CIRCUS_REF:-48154ea1}        # circus main 2026-10-18: T2 integration, 2 ms timestep, --no-images
SIMBRIDGE_REF=${SIMBRIDGE_REF:-ce708bfa}  # simbridge main 2026-10-18: the matching shared-memory layout
# simbridge polls circus's state segment every POLL_US. circus waits for every robot's command on each physics substep
# (RobotManager::receiveCommandMessagesSHM, checking every 200 us), so this poll is on the critical path of the
# lockstep: the upstream 1 us busy-spins one core per robot (the 10-robot stall on Modal), and 1 ms would use up to half
# of a 2 ms substep. 200 us matches circus's own check. Tune with SIMBRIDGE_POLL_US after measure_rtf.sh.
POLL_US=${SIMBRIDGE_POLL_US:-200}
SPQR=${SPQR:-/DATA/RoboCup/spqrbooster2026}  # the robot framework tree to build (e.g. a merge clone on another disk)
ORA=/DATA/RoboCup/oraculum
HERE=$(cd "$(dirname "$0")" && pwd)

ssh "$VM" 'command -v rsync >/dev/null && command -v git >/dev/null || (apt-get update -q && apt-get install -yq rsync git)
           mkdir -p /workspace /opt/circus /opt/oraculum /opt/session'

# 1. Robot framework working tree (with the uncommitted oraculum work), without environments, builds and submodules
rsync -a --delete --exclude=.pixi --exclude=/build --exclude=.git --exclude=.codegraph \
    --exclude=/external/circus --exclude=/external/simbridge --exclude=/external/GameController "$SPQR/" "$VM:/workspace/"

# 2. simbridge is private: stream its tarball from GitHub (through gh's login) into the VM. Never copy the local
#    checkout: it is stale (d1df86d) and its library links are NTFS stub files.
gh api "repos/SPQRTeam/simbridge/tarball/$SIMBRIDGE_REF" | ssh "$VM" \
    'rm -rf /workspace/external/simbridge && mkdir -p /workspace/external/simbridge &&
     tar -xz --strip-components=1 -C /workspace/external/simbridge'
ssh "$VM" bash -s -- "$POLL_US" <<'EOF'
f=/workspace/external/simbridge/src/bridge_node.hpp
sed -i -E "s/socket_recv_timeout \{ 0, [0-9]+ \};/socket_recv_timeout { 0, $1 };/; s/sim2frw_period = [0-9]+us;/sim2frw_period = ${1}us;/" "$f"
[ "$(grep -cE "socket_recv_timeout \{ 0, $1 \};|sim2frw_period = ${1}us;" "$f")" = 2 ] \
    || { echo "simbridge poll edit failed in $f" >&2; exit 1; }
EOF

# 3. circus is public: the VM clones it
ssh "$VM" "rm -rf /opt/circus && git clone -q https://github.com/SPQRTeam/circus.git /opt/circus &&
           git -C /opt/circus checkout -q --detach $CIRCUS_REF"
# Opt-in test only: CIRCUS_JACOBIAN=sparse swaps circus's dense constraint Jacobian (src/SceneParser.cpp) for sparse,
# less solver work with many robots. Default (unset): circus as upstream. Revert: push again without the variable, or
# on the VM: git -C /opt/circus checkout src/SceneParser.cpp, then rebuild circus.
if [ -n "${CIRCUS_JACOBIAN:-}" ]; then
    ssh "$VM" "sed -i 's/append_attribute(\"jacobian\") = \"dense\"/append_attribute(\"jacobian\") = \"$CIRCUS_JACOBIAN\"/' /opt/circus/src/SceneParser.cpp &&
               [ \$(grep -c 'append_attribute(\"jacobian\") = \"$CIRCUS_JACOBIAN\"' /opt/circus/src/SceneParser.cpp) = 1 ]" \
        || { echo "circus jacobian edit failed" >&2; exit 1; }
fi

# 4. oraculum gateway and pages (the git-ignored 3D assets in src/static come along)
rsync -a --delete --exclude=__pycache__ --exclude=recordings \
    "$ORA/src" "$ORA/fields" "$ORA/config" "$ORA/config.yaml" "$VM:/opt/oraculum/"

# 5. session scripts, systemd unit and scenes
rsync -a "$HERE/" "$ORA/hosted/scenes/" "$VM:/opt/session/"
echo "pushed: circus $CIRCUS_REF (jacobian ${CIRCUS_JACOBIAN:-upstream}), simbridge $SIMBRIDGE_REF, simbridge poll ${POLL_US} us"
echo "next:   ssh $VM /opt/session/provision.sh"
