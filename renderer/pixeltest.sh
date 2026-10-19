#!/usr/bin/env bash
# One pixel-test job of .github/workflows/oraculum-renderer.yml; runs the same way on a laptop (README.md).
# Usage, from the repository root: renderer/pixeltest.sh SCENE DEPTH CHECK [QUERY]
#   SCENE: maximus_5v5 | maximus_1v1    DEPTH: ext | d24    QUERY: extra page parameters (negative test)
#   CHECK msaa:  the look of the pages (4x MSAA, as circus's window) against the native 4x MSAA references
#                of two GPUs in refs_msaa/<scene>/ (msaa_refs.py; a render must be within the bounds against one): >= 31.5 dB,
#                < 3 % of pixels off by more than 16, >= 90 % of the white line pixels kept (ext: SwiftShader's own
#                MSAA, measured 32.1 dB, 95 %). d24 (b2.js's 4 jittered passes): >= 36 dB, < 2 %, >= 97 % (measured
#                2026-10-12: 37.6 dB, 1.2 %, 98.6 %; the old 2x2 supersample with its line stipple: 33.5 dB, 93.3 %).
#                Exit 4 when the references were made from another scene ("reference out of date").
#   CHECK exact: no MSAA on either side, against MuJoCo on OSMesa (refs job, refs/). SwiftShader and llvmpipe
#                rasterize a little differently (measured 2026-10-12: d24 36.8-38.8 dB, 0.08-0.11 % px > 16;
#                ext 30.3-33.8 dB, 0.25-0.63 %: SwiftShader's own depth format), so the bar depends on DEPTH.
# Needs site/b2_bundle/ (build job), site/b2_scenes/<scene>/ (scene job) and, for exact, refs/.
# Exit codes: shot.py's (0 pass, 3 pixel test failed, 4 reference out of date, 2 other failure).
set -euo pipefail
SCENE=$1 DEPTH=$2 CHECK=$3 QUERY=${4:-}
cd "$(dirname "$0")"
out="../results/$SCENE-$DEPTH-$CHECK"
common=(--depth "$DEPTH" --scene "../b2_scenes/$SCENE" --query "$QUERY")
if [ "$CHECK" = msaa ]; then
  msaa_bar=(--min-psnr 31.5 --max-pct16 3 --min-line-keep 90)
  if [ "$DEPTH" = d24 ]; then msaa_bar=(--min-psnr 36 --max-pct16 2 --min-line-keep 97); fi
  poses=poses.json
  if [ "$SCENE" = maximus_1v1 ]; then poses=poses_1v1.json; fi
  exec python3 shot.py ../site "$poses" "refs_msaa/$SCENE" "$out" "${common[@]}" --aa 1 \
    --ref-pattern "{pose}_{size}_rtx.png" "{pose}_{size}_arc.png" --scene-sha256 "refs_msaa/$SCENE/scene.sha256" \
    "${msaa_bar[@]}"
fi
bar=(--min-psnr 36 --max-pct16 0.2)
if [ "$DEPTH" = ext ]; then bar=(--min-psnr 29.5 --max-pct16 1); fi
exec python3 shot.py ../site "../refs/poses_$SCENE.json" ../refs "$out" "${common[@]}" --aa 0 "${bar[@]}"
