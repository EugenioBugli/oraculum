#!/usr/bin/env bash
# Rebuild the standalone MuJoCo scene folders from a circus commit, with circus's own code.
#
# usage: export_scene.sh <circus-ref> <out-dir> [scene.yaml ...]
#   circus-ref  branch, tag or commit of https://github.com/SPQRTeam/circus (default: main)
#   out-dir     gets one folder circus_scene_<yaml-name>/ per scene
#   scene.yaml  paths inside the circus tree (default: resources/scenes/1v1.yaml resources/scenes/5v5.yaml)
#
# env: WORK (build dir, kept for reuse; default a new temp dir), JOBS (default 2),
#      CIRCUS_URL (default the public repo), PYTHON (needs mujoco==3.3.3; default python3),
#      FRAMEWORK_PATH (a maximus checkout: circus then reads field and simulation configs
#      from it, exactly as `pixi run sim` in spqrbooster2026 does; unset = circus's own configs).
# needs: git, pixi, $PYTHON with mujoco==3.3.3 + PyOpenGL, and MUJOCO_GL=osmesa|egl for the render.
set -euo pipefail

TOOLS=$(cd "$(dirname "$0")" && pwd)
REF=${1:-main}
OUT=$(realpath -m "${2:-./scene-out}")
shift $(( $# < 2 ? $# : 2 ))
SCENES=("$@")
[ ${#SCENES[@]} -gt 0 ] || SCENES=(resources/scenes/1v1.yaml resources/scenes/5v5.yaml)
WORK=${WORK:-$(mktemp -d)}
CIRCUS=$WORK/circus
PYTHON=${PYTHON:-python3}

if [ ! -d "$CIRCUS/.git" ]; then
  git clone --filter=blob:none "${CIRCUS_URL:-https://github.com/SPQRTeam/circus.git}" "$CIRCUS"
fi
git -C "$CIRCUS" fetch --quiet origin
git -C "$CIRCUS" checkout --quiet --detach "$(git -C "$CIRCUS" rev-parse --verify --quiet "origin/$REF" || echo "$REF")"
COMMIT=$(git -C "$CIRCUS" rev-parse HEAD)
echo "circus $REF = $COMMIT"

cd "$CIRCUS"
pixi install --frozen
# Same configure as circus's `pixi run configure`, plus the exporter hook; no Python bindings.
pixi run -- cmake -S "$CIRCUS" -B "$CIRCUS/build-export" -DBUILD_PYTHON_BINDINGS=OFF \
  -DCMAKE_PREFIX_PATH="$CIRCUS/.pixi/envs/default" \
  -DCMAKE_PROJECT_circus_INCLUDE="$TOOLS/exporter.cmake" > "$WORK/configure.log"
pixi run -- cmake --build "$CIRCUS/build-export" --target circus_scene_export -j"${JOBS:-2}"

mkdir -p "$OUT"
for scene in "${SCENES[@]}"; do
  name=$(basename "$scene" .yaml)
  pixi run -- "$CIRCUS/build-export/circus_scene_export" "$scene" > "$WORK/$name.raw.xml"
  "$PYTHON" "$TOOLS/package_scene.py" "$WORK/$name.raw.xml" "$CIRCUS" "$OUT/circus_scene_$name" \
    --commit "$COMMIT" --scene-yaml "$scene"
done
