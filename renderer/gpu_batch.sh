#!/usr/bin/env bash
# fps of the bundle on this laptop's two GPUs, each depth mode; records load and Intel throttling.
# Usage: ARIA_LOCAL_OK=1 ./gpu_batch.sh BASE_URL OUT_DIR TAG   (bundle served at BASE_URL)
set -u
BASE=$1; OUT=$2; TAG=$3
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
NV="__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
for gpu in intel rtx; do
  for depth in ext d24 fragdepth; do
    env_prefix=""; [ "$gpu" = rtx ] && env_prefix=$NV
    echo "== $gpu $depth load=$(cut -d' ' -f1 /proc/loadavg) pl1=$(cat /sys/class/drm/card1/gt/gt0/throttle_reason_pl1 2>/dev/null)"
    shots=""; [ "$depth" != fragdepth ] && shots="--shots $OUT/${TAG}_${gpu}_${depth}"
    env $env_prefix python3 "$HERE/gpu_fps.py" "$BASE" "$OUT/${TAG}_${gpu}_${depth}.json" --depth "$depth" $shots 2>&1 \
      | python3 -c 'import sys, json
for l in sys.stdin:
    try: r = json.loads(l)
    except Exception: continue
    print(r["size"], r.get("depth_mode"), "fps", r.get("fps_raf_5s"), "ms_sync", r.get("ms_per_frame_sync"), "ms_queued", r.get("ms_per_frame_queued"), "cpu_ms", round(r.get("stats", {}).get("frameCpuMs", 0), 1), r.get("renderer", "")[:60])'
  done
done
