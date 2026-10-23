#!/bin/bash
# Build Maximus natively for aarch64 on the Jetson. It runs in a container because the tree must be at /workspace
# (PROJECT_ROOT, pixi prefixes and RPATHs are absolute; the robot containers mount it there) and we have no sudo.
# Output: ~/oraculum-sim-arm/workspace/build/arm/src/app/maximus_main. CMake build type as x86 (default Debug).
set -euo pipefail
# BUILD_TYPE=Release -> build/arm-release (selected at run time by the file build/USE_RELEASE, supervisord.arm.conf);
# default: the CMake default (Debug -O0, as on x86) in build/arm.
BDIR=arm; BTYPE=""
[ "${BUILD_TYPE:-}" = Release ] && BDIR=arm-release && BTYPE="-DCMAKE_BUILD_TYPE=Release"
W=${W:-$HOME/oraculum-sim-arm}
mkdir -p "$W/home" "$W/cache"
docker run --rm --network host --entrypoint "" --user "$(id -u):$(id -g)" \
    -e HOME=/home/builder -v "$W/home:/home/builder" -v "$W/workspace:/workspace" -v "$W/pixi:/pixi:ro" \
    -v "$W/cache:/cache" -e PIXI_CACHE_DIR=/cache/pixi -e BDIR="$BDIR" -e BTYPE="$BTYPE" -e CONDA_OVERRIDE_CUDA=12.0 -w /workspace ros:humble \
    bash -c 'set -e; t0=$(date +%s); /pixi/bin/pixi install; echo "pixi install: $(( $(date +%s) - t0 )) s"
             /pixi/bin/pixi run bash -c "cmake -S /workspace -B /workspace/build/$BDIR -G Ninja -DCMAKE_PREFIX_PATH=\$CONDA_PREFIX -DENABLE_TENSORRT=OFF $BTYPE \
                 && cmake --build /workspace/build/$BDIR --parallel ${JOBS:-10}"
             echo "maximus total: $(( $(date +%s) - t0 )) s"'
