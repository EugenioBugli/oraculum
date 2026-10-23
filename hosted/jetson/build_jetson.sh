#!/bin/bash
# Build the hosted simulation on the Jetson (aarch64). Runs ON the Jetson in ~/oraculum-sim-arm, after build_all.sh
# (laptop) has copied these scripts and the private sources (workspace/, oraculum/) there. No sudo, nothing system-wide.
#   ~/oraculum-sim-arm/build_jetson.sh            # builds everything, then a 30 s 1-robot smoke test
#   Native booster-motion (the default) needs the T1 firmware: 3.9 GB download + unpack on the first build.
#   NATIVE=0 ...  skips it (then only the Box64 path works: BOOSTER_MOTION=box64)
# Steps run in parallel where they can; each logs to logs/build_<step>.log with its wall time.
set -euo pipefail
W=$HOME/oraculum-sim-arm
cd "$W"
mkdir -p logs ctx ctx-display cache
export PATH=$W/pixi/bin:$PATH PIXI_CACHE_DIR=$W/cache/pixi
CIRCUS_REF=${CIRCUS_REF:-31a7b67a}   # camera-info-fix; must match simbridge 625336d2
step() { local name=$1; shift; local t0; t0=$(date +%s)
         if "$@" > "logs/build_$name.log" 2>&1; then echo "$name: ok, $(( $(date +%s) - t0 )) s"
         else echo "$name: FAILED after $(( $(date +%s) - t0 )) s, see $W/logs/build_$name.log"; return 1; fi; }

# 0. tools: pixi (user-local) and Box64 (x86_64 -> arm64 for the closed booster-motion)
[ -x pixi/bin/pixi ] || curl -fsSL https://pixi.sh/install.sh | PIXI_HOME=$W/pixi PIXI_VERSION=v0.82.1 PIXI_NO_PATH_UPDATE=1 bash
if [ ! -x box64 ]; then
    if [ -x "$HOME/box64/build/box64" ]; then cp "$HOME/box64/build/box64" box64
    else  # not tested here: the Jetson already had ~/box64/build/box64 (v0.3.6)
        git clone -q --depth 1 -b v0.3.6 https://github.com/ptitSeb/box64 box64-src
        "$HOME/opt/cmake/bin/cmake" -S box64-src -B box64-src/build -DARM_DYNAREC=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
        "$HOME/opt/cmake/bin/cmake" --build box64-src/build -j 10 && cp box64-src/build/box64 box64
    fi
fi

# 1. simbridge camera-info fix (625336d2) on the server's ce708bfa tree, unless the copied tree has it already
(cd workspace/external/simbridge
 if patch -p1 -R --dry-run -s -f < "$W/simbridge_625336d2.patch" >/dev/null 2>&1; then echo "simbridge: 625336d2 already in"
 else patch -p1 -N -s < "$W/simbridge_625336d2.patch" && echo "simbridge: 625336d2 applied"; fi)

# 1b. Maximus with booster-motion 1.8 in simulation (SPQR_SIM_FW18, set by supervisord.arm.conf on the native path):
#     kSoccer instead of kWalking + Prepare at boot. Same change as uncommitted in /home/xps/work/spqr-merge.
(cd workspace
 if patch -p1 -R --dry-run -s -f < "$W/maximus_sim_fw18.patch" >/dev/null 2>&1; then echo "maximus: sim_fw18 already in"
 else patch -p1 -N -s < "$W/maximus_sim_fw18.patch" && echo "maximus: sim_fw18 applied"; fi)

# 2. robot framework edits for arm64 (pixi compilers, supervisord with Box64 + native Maximus, optional GPU, timing log)
(cd workspace && bash "$W/patch_maximus.sh" && bash "$W/patch_entrypoint.sh" && bash "$W/patch_detector_timing.sh" \
    && bash "$W/patch_fall_logging.sh")
[ -f workspace/scripts/supervisord.conf.x86 ] || cp workspace/scripts/supervisord.conf workspace/scripts/supervisord.conf.x86
cp supervisord.arm.conf workspace/scripts/supervisord.conf

# 3. build context of the robot image: Box64, the data-sharing-free x86 libfastrtps, Dockerfile
cp box64 Dockerfile.robot ctx/
python3 patch_fastrtps.py workspace/external/simbridge/tools/booster_motion/lib-usr-local/libfastrtps.so.2.13 ctx/libfastrtps.so.2.13
cp Dockerfile.display ctx-display/Dockerfile
# The base image copies only external/simbridge/* and docker_bashrc_addendum: keep the GBs of .pixi/build/models (and
# Maximus writing build/arm in parallel) out of the build context
printf '.pixi\nbuild\nmodels\n' > workspace/.dockerignore

# 4. the long builds in parallel: circus (~2 min), robot image (~6 min), Maximus (~6.5 min), display image (~1 min)
circus() {
    [ -d circus/.git ] || git clone -q https://github.com/SPQRTeam/circus.git circus
    git -C circus fetch -q origin && git -C circus checkout -q -f --detach "$CIRCUS_REF"
    (cd circus && bash "$W/patch_circus.sh" && bash "$W/patch_circus_ballpos.sh" && pixi install && rm -rf build \
        && JOBS=10 pixi run compile)
}
robot_image() {   # the x86 Dockerfile unchanged (FROM ros:humble resolves to arm64), then our layer
    # (&&: set -e is off inside a function called from `if`; the robot layer must not build on an old base)
    docker build --network host -t oraculum-arm-base workspace &&
        docker build --network host -t oraculum-arm-robot -f ctx/Dockerfile.robot ctx
}
pids=()
step circus circus & pids+=($!)
step robot_image robot_image & pids+=($!)
step maximus bash build_maximus.sh & pids+=($!)
step display_image docker build --network host -t oraculum-arm-display ctx-display & pids+=($!)
fail=0; for p in "${pids[@]}"; do wait "$p" || fail=1; done
[ $fail = 0 ] || { echo "a build failed" >&2; exit 1; }

# 5. GPU libraries for the robot containers (docker_config.gpu.yaml): cuDNN 9.3 + TensorRT 10.3 from the host
mkdir -p gpulibs && cp -au /usr/lib/aarch64-linux-gnu/{libcudnn*,libnvinfer*,libnvonnxparser*}.so* gpulibs/
rm -f gpulibs/*_static.a

# 6. native aarch64 booster-motion from the T1 firmware (the default path; JETSON.md section 17)
if [ "${NATIVE:-1}" != 0 ]; then
    fw=1.8.0.9-release-02011-2026-09-14-global.22.04.aarch64-unsealed.single.run
    mkdir -p dl fw-1.8.0.9
    [ -f "dl/$fw" ] || step fw_download ./fetch_ranges.sh \
        "https://boosterobotics.s3.ap-southeast-1.amazonaws.com/ota_single/5dc1e2ab/$fw" "dl/$fw" 3909080772 16
    [ -x fw-1.8.0.9/booster/bin/booster-motion ] || tail -c 3909061785 "dl/$fw" | zstd -cd \
        | tar -x -C fw-1.8.0.9 --wildcards "./booster/bin/*" "./booster/lib/*" "./booster/Gait/*" "./booster/configs/*"
    if [ ! -x booster-native/bin/booster-motion ]; then
        mkdir -p booster-native/bin booster-native/fwlib
        cp -a fw-1.8.0.9/booster/bin/booster-motion booster-native/bin/
        cp -a fw-1.8.0.9/booster/lib/motion booster-native/bin/lib
        cp -a fw-1.8.0.9/booster/Gait/configs booster-native/configs
        printf "Model Version: 1.0.0\n" > booster-native/robot_info.txt
        printf "Model Version: 2.3.4\n" > booster-native/robot_info_2.3.4.txt   # docker_config.native_parity.yaml
    fi
    # PD loop + IMU flag + serial-ankle bypass for circus (BOOSTER_MOTION_RE.md); supervisord.arm.conf runs this config
    cp config_sim_circus.lua booster-native/configs/T1/
fi

# 7. smoke test: 1 robot, 30 simulated seconds, sim_fast, default booster-motion (native unless NATIVE=0), with a clip
chmod +x ./*.sh
BM=native; [ "${NATIVE:-1}" = 0 ] && BM=box64
BOOSTER_MOTION=$BM RUN_NAME=build_smoke_$BM SCENE=$W/scenes/1v0.yaml SIM_S=30 ./measure_rtf.sh > logs/build_smoke.log 2>&1 || true
grep "real-time factor" logs/build_smoke.log || { echo "smoke test FAILED, see $W/logs/build_smoke.log"; exit 1; }
