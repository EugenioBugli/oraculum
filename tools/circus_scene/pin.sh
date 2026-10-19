#!/usr/bin/env bash
# Copies the two folders circus reads from the framework (src/app/sim, src/app/config/fields) out of a
# spqrbooster2026 checkout at a commit into tools/circus_scene/pinned/, with PIN (commits and git tree hashes).
# The scene workflow then needs no access to the private spqrbooster2026. Run it when those folders or the circus
# submodule change on spqrbooster2026, then commit pinned/.
# usage: tools/circus_scene/pin.sh [<maximus-dir>] [<commit>]   (defaults: ../spqrbooster2026, main)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
dir=${1:-$here/../../../spqrbooster2026}
ref=${2:-main}
out=$here/pinned
rm -rf "$out" && mkdir -p "$out"
git -C "$dir" archive "$ref" src/app/sim src/app/config/fields | tar -x -C "$out"
{
  echo "spqrbooster2026=$(git -C "$dir" rev-parse "$ref")"
  echo "circus=$(git -C "$dir" rev-parse "$ref:external/circus")"
  echo "sim_tree=$(git -C "$dir" rev-parse "$ref:src/app/sim")"
  echo "fields_tree=$(git -C "$dir" rev-parse "$ref:src/app/config/fields")"
} > "$out/PIN"
cat "$out/PIN"
