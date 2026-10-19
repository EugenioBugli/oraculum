#!/bin/bash
# Assemble the build folder of the hosted-session image from local files: the uncommitted robot-side and oraculum
# work goes in as it is, nothing is pushed. circus and simbridge come at the commits spqrbooster2026 HEAD pins,
# circus with circus_process_robots.patch (robots as processes: Modal has no Docker).
#   hosted/stage.sh [STAGE]     default STAGE=/tmp/oraculum-hosted-stage
set -euo pipefail
STAGE=${1:-/tmp/oraculum-hosted-stage}
case "$STAGE" in */oraculum-hosted-stage) ;; *) echo "STAGE must end with /oraculum-hosted-stage" >&2; exit 1;; esac
SPQR=${SPQR:-/DATA/RoboCup/spqrbooster2026}
HERE=$(cd "$(dirname "$0")" && pwd)
ORA=$(dirname "$HERE")
EMPTY=$(mktemp -d)
mkdir -p "$STAGE/spqrbooster2026" "$STAGE/circus" "$STAGE/oraculum"

# robot framework (working tree, without environments, builds and the submodules replaced below)
rsync -a --delete --exclude=.pixi --exclude=/build --exclude=.git --exclude=.codegraph \
    --exclude=/external/circus --exclude=/external/simbridge --exclude=/external/GameController \
    "$SPQR/" "$STAGE/spqrbooster2026/"

pin() { git -C "$SPQR" ls-tree HEAD "$1" | awk '{print $3}'; }
export_at() {  # $1 repo dir, $2 commit, $3 destination (replaced)
    local tmp; tmp=$(mktemp -d)
    git -C "$1" archive "$2" | tar -x -C "$tmp"
    mkdir -p "$3"
    rsync -a --delete "$tmp/" "$3/"
    rsync -a --delete "$EMPTY/" "$tmp/" && rmdir "$tmp"
}
export_at "$SPQR/external/simbridge" "$(pin external/simbridge)" "$STAGE/spqrbooster2026/external/simbridge"
export_at "$SPQR/external/circus" "$(pin external/circus)" "$STAGE/circus"
(cd "$STAGE/circus" && patch -p1 --forward < "$HERE/circus_process_robots.patch")

# oraculum gateway and pages (with the git-ignored 3D assets)
rsync -a --delete --exclude=__pycache__ --exclude=recordings "$ORA/src" "$ORA/fields" "$ORA/config" "$ORA/config.yaml" "$STAGE/oraculum/"
rmdir "$EMPTY"
echo "stage ready: $STAGE (circus $(pin external/circus | cut -c1-7), simbridge $(pin external/simbridge | cut -c1-7))"
du -sh "$STAGE"/*
