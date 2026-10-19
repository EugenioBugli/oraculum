#!/usr/bin/env bash
# Prints the version tag of the circus scene for a spqrbooster2026 (maximus) checkout:
#   circus-scene-<circus commit, 12>-<config id, 12>
# The config id hashes the git trees of the two folders circus reads from the framework
# (src/app/sim, src/app/config/fields) at HEAD, so uncommitted edits do not change it.
# Used by .github/workflows/circus-scene.yml and tools/fetch_circus_scene.py: one definition.
# usage: scene_tag.sh <maximus-dir> [--config-only]
set -euo pipefail
dir=${1:?usage: scene_tag.sh <maximus-dir> [--config-only]}
trees="$(git -C "$dir" rev-parse HEAD:src/app/sim):$(git -C "$dir" rev-parse HEAD:src/app/config/fields)"
config=$(printf '%s' "$trees" | sha256sum | cut -c1-12)
if [ "${2:-}" = "--config-only" ]; then
  echo "$config"
else
  echo "circus-scene-$(git -C "$dir" rev-parse HEAD:external/circus | cut -c1-12)-$config"
fi
