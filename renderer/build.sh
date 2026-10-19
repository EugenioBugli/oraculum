#!/usr/bin/env bash
# Build the B2 renderer bundle: MuJoCo <version> (engine + classic renderer, unmodified) compiled to
# WebAssembly against the B2 GL shim, plus the WebGL2 replay (b2.js) and the test page.
# Scene packages are made by package_scenes.sh (no compiler needed).
#
# Usage:   ./build.sh MUJOCO_VERSION OUT_DIR
# Example: ./build.sh 3.3.3 b2_bundle
# Runs inside an Emscripten SDK environment (emcc on PATH, e.g. the emscripten/emsdk:3.1.74 image);
# needs git and python3. Env: JOBS (default nproc), MJ_SRC (MuJoCo checkout to reuse),
# BUILD (cmake build dir, default ./build).
set -euo pipefail

MJ_VERSION=${1:?MuJoCo version (git tag), e.g. 3.3.3}
OUT=${2:?output folder}
HERE=$(cd "$(dirname "$0")" && pwd)
JOBS=${JOBS:-$(nproc)}
BUILD=${BUILD:-$HERE/build}
MJ_SRC=${MJ_SRC:-$HERE/src/mujoco-$MJ_VERSION}
T0=$(date +%s)

[ -d "$MJ_SRC" ] || git clone -q --depth 1 --branch "$MJ_VERSION" https://github.com/google-deepmind/mujoco.git "$MJ_SRC"
mkdir -p "$BUILD" "$OUT"
MJ_BUILD=$BUILD/mujoco-$MJ_VERSION

# MuJoCo with its own CMake (flags only, as in Spike A). The classic renderer is part of the
# "mujoco" target; it is linked unchanged and talks to the shim through its glad loader.
emcmake cmake -S "$MJ_SRC" -B "$MJ_BUILD" -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF -DMUJOCO_BUILD_EXAMPLES=OFF -DMUJOCO_BUILD_SIMULATE=OFF \
  -DMUJOCO_BUILD_TESTS=OFF -DMUJOCO_TEST_PYTHON_UTIL=OFF \
  -DMUJOCO_ENABLE_AVX=OFF -DMUJOCO_ENABLE_AVX_INTRINSICS=OFF \
  -DCMAKE_INTERPROCEDURAL_OPTIMIZATION_RELEASE=OFF -DLIBM_LIBRARY=m -DCMAKE_SKIP_INSTALL_RULES=ON \
  -DCMAKE_CXX_FLAGS="-fexceptions" >"$BUILD/cmake-mujoco.log"
cmake --build "$MJ_BUILD" --target mujoco -j"$JOBS"

# Typed fallbacks for every GL entry point of this MuJoCo version's glad loader.
python3 "$HERE/src_b2/gen_stubs.py" "$MJ_SRC" "$BUILD/glstubs.c"

DBG=""; [ "${DEBUG:-0}" = 1 ] && DBG="--profiling-funcs -sASSERTIONS=1"
# shellcheck disable=SC2046
emcc -O2 $DBG "$HERE/src_b2/main.c" "$HERE/src_b2/glshim.c" "$BUILD/glstubs.c" \
  -I"$MJ_SRC/include" -I"$MJ_SRC/src" -I"$HERE/src_b2" \
  $(find "$MJ_BUILD" -name '*.a' | sort) \
  -fexceptions -sALLOW_MEMORY_GROWTH=1 -sMEMORY_GROWTH_LINEAR_STEP=16MB -sSTACK_SIZE=5MB -sFORCE_FILESYSTEM=1 \
  -sMODULARIZE=1 -sEXPORT_NAME=createB2Engine -sENVIRONMENT=web \
  -sEXPORTED_FUNCTIONS=_b2_load,_b2_nq,_b2_qpos,_b2_lists,_b2_free_vertices,_b2_camera,_b2_frame,_b2_texture_name,_b2_time_update,_b2_time_render,_b2_unimplemented,_b2_unsupported,_b2_name2id,_b2_geom_rgba,_b2_geom_half_z,_b2_hide_bodies,_b2_set_flag,_b2_set_geomgroup,_b2_move_camera,_b2_get_camera \
  -sEXPORTED_RUNTIME_METHODS=FS,ccall,HEAPU8,HEAP32,HEAPU32,HEAPF32,HEAPF64 \
  -o "$OUT/b2_engine.js"
cp "$HERE/src_b2/b2.js" "$HERE/src_b2/index.html" "$OUT/"
for f in poses.json poses_1v1.json; do if [ -f "$HERE/$f" ]; then cp "$HERE/$f" "$OUT/"; fi; done

echo "MuJoCo $MJ_VERSION, emcc $(emcc --version | head -1 | grep -o '[0-9]*\.[0-9]*\.[0-9]*' | head -1), built in $(( $(date +%s) - T0 )) s" | tee "$OUT/BUILD_INFO.txt"
ls -l "$OUT"
