#!/usr/bin/env bash
# Fetches the large assets of the WASM 3D view into src/static/ (they are not in git):
#   src/static/mujoco/          MuJoCo WebAssembly build (npm package @mujoco/mujoco)
#   src/static/models/booster_t1/  Booster T1 MJCF + meshes, taken from a circus checkout
# Usage: tools/fetch_web_assets.sh [CIRCUS_DIR] [CIRCUS_REF]
set -euo pipefail

MUJOCO_VERSION=3.14.0
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CIRCUS_DIR="${1:-$ROOT/../circus}"
CIRCUS_REF="${2:-origin/main}"
STATIC="$ROOT/src/static"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# MuJoCo WASM (single-thread build: no COOP/COEP headers needed on the gateway)
npm pack "@mujoco/mujoco@$MUJOCO_VERSION" --pack-destination "$TMP" >/dev/null
tar xzf "$TMP"/mujoco-mujoco-"$MUJOCO_VERSION".tgz -C "$TMP"
mkdir -p "$STATIC/mujoco"
cp "$TMP/package/mujoco.js" "$TMP/package/mujoco.wasm" "$STATIC/mujoco/"
echo "$MUJOCO_VERSION" > "$STATIC/mujoco/VERSION"

# Booster T1 model from circus (same files the simulator loads)
git -C "$CIRCUS_DIR" archive "$CIRCUS_REF" resources/robots/Booster-T1 resources/meshes/Booster-T1 \
  | tar x -C "$TMP"
OUT="$STATIC/models/booster_t1"
rm -rf "$OUT" && mkdir -p "$OUT/meshes"
cp "$TMP/resources/robots/Booster-T1/"*.xml "$OUT/"
# Drop the jersey-digit geoms and meshes (1.3 MB): the page shows the number as a label.
sed -i '/Booster-T1_num_/d' "$OUT"/*.xml
# Copy only the meshes that common.xml references (meshdir = meshes/, "../meshes/x" = "x").
grep -o 'file="[^"]*"' "$OUT/common.xml" | sed -e 's/^file="//' -e 's/"$//' -e 's#^\.\./meshes/##' -e 's#^#meshes/#' > "$OUT/files.txt"
while read -r f; do
  mkdir -p "$OUT/$(dirname "$f")"
  cp "$TMP/resources/${f}" "$OUT/$f"
done < "$OUT/files.txt"
git -C "$CIRCUS_DIR" rev-parse "$CIRCUS_REF" > "$OUT/CIRCUS_COMMIT"
du -sh "$STATIC/mujoco" "$OUT"
