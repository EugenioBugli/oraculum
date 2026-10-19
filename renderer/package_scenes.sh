#!/usr/bin/env bash
# Scene packages for B2Viewer.load(url): each circus scene folder (tools/circus_scene export:
# scene.xml, scene_index.json, assets/) is copied to OUT_ROOT/<name>/ with files.json, the list of
# files the viewer downloads into MuJoCo's virtual file system.
#
# Usage:   ./package_scenes.sh OUT_ROOT SCENE_DIR[:NAME] [SCENE_DIR[:NAME] ...]
# Example: ./package_scenes.sh b2_scenes ../scene/circus_scene_maximus_5v5 out/circus_scene_5v5:maximus_5v5
# Without :NAME, a folder circus_scene_<name> becomes OUT_ROOT/<name>.
set -euo pipefail
OUT=${1:?output folder}
shift
for arg in "$@"; do
  src=${arg%%:*}
  name=${arg#*:}
  if [ "$name" = "$arg" ]; then name=$(basename "$src"); name=${name#circus_scene_}; fi
  [ -f "$src/scene.xml" ] || { echo "no scene.xml in $src" >&2; exit 1; }
  dst=$OUT/$name
  mkdir -p "$dst"
  (cd "$src" && find . -type f ! -name reference.png ! -name files.json ! -name MUJOCO_LOG.TXT | sed 's|^\./||' | LC_ALL=C sort) > "$dst/files.json.txt"
  while read -r f; do mkdir -p "$dst/$(dirname "$f")"; cp "$src/$f" "$dst/$f"; done < "$dst/files.json.txt"
  python3 -c 'import json,sys; print(json.dumps({"files": [l.strip() for l in open(sys.argv[1]) if l.strip()]}))' \
    "$dst/files.json.txt" > "$dst/files.json"
  rm "$dst/files.json.txt"
  echo "$dst: $(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["files"]))' "$dst/files.json") files, $(du -sh "$dst" | cut -f1)"
done
