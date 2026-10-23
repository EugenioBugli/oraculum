# Hosted simulation on the team Jetson (aarch64)

Goal: circus + simulated Booster T1 robots + oraculum gateway on the team's Jetson AGX Orin, without the x86 server.
Milestones: 1 robot standing and walking (with real-time factor), then 1v1, then 2v2.

## Summary (2026-10-22 evening)

- Everything runs on the Jetson: circus (native aarch64, llvmpipe), gateway, arm64 robot containers.
- **Default since 2026-10-22 ~20:00 (user decision): the NATIVE aarch64 booster-motion** from the T1 firmware
  1.8.0.9 with `config_sim_circus.lua` (`docker_config.yaml`). Box64 + the x86 0.0.11 package is opt-in for
  comparison runs: `BOOSTER_MOTION=box64` (`docker_config.box64.yaml`). GPU for Maximus's NNs: `GPU=1`
  (`docker_config.gpu.yaml`, Box64: `docker_config.box64_gpu.yaml`). The image still contains Box64 and the patched
  x86 FastDDS; only the Box64 path uses them.
- File names used in the log below before the switch: old `docker_config.yaml` = now `docker_config.box64.yaml`,
  old `docker_config.gpu.yaml` = now `docker_config.box64_gpu.yaml`, old `docker_config.native.yaml` = now
  `docker_config.yaml`, old `docker_config.native_gpu.yaml` = now `docker_config.gpu.yaml`.
- **Start fall fixed (2026-10-22 ~20:15):** `SPQR_SIM_FW18` (Maximus uses kSoccer = RobocupMode and sends Prepare at
  boot; uncommitted in `/home/xps/work/spqr-merge`) + simbridge waits for Prepare. Native runs since then: 0 falls in
  1v0 sim_fast (RTF 0.69), 1v1 sim_fast (0.40), 1v0 sim_real GPU (0.45 Debug, **0.65 Release**). Section
  "Start-fall fix" at the end.
- Fastest chain: `bash /DATA/RoboCup/oraculum/hosted/jetson/build_all.sh` (section "Build chain").

| Real-time factor (MODE_50W, shared machine) | Box64 | Native |
|---|---|---|
| 1 robot, sim_fast | 0.56-0.58 | 0.74-0.90 |
| 1v1, sim_fast | 0.36 (0.29 with the Ghidra job) | 0.36 |
| 2v2, sim_fast | 0.16 | not run |
| 1 robot, sim_real, GPU YOLO | 0.46-0.52 (one run 0.34) | 0.48 (one run 0.28, Ghidra job) |
| 1 robot, sim_real, CPU YOLO | 0.28 | - |
| 1v1, sim_real, GPU YOLO | 0.29 | not run |

- YOLO detector: TensorRT on the Orin GPU 19-21 ms per frame (Maximus 70-140 % CPU); ONNX Runtime on the CPU
  887 ms (Maximus 716 % CPU).
- Build times (cold): copy 28 s + 6 s, circus 119 s, robot base image 5 min 37 s, Maximus 388 s, display image
  185 s; end to end with a warm Docker cache 580 s.
- Falls: native falls once at the first PLAYING step (mode mapping SDK 1.7.0 vs firmware 1.8 is the lead), gets up,
  then plays. Box64 sim_real: no `rt/odometer_state` reaches Maximus, so no self-localization, then fast backward
  walking and falls. Timing alone: not shown either way. Contacts: one native 1v1 fall. Details: "Fall analysis".
- Clips of the runs from 19:2x on: `/DATA/RoboCup/oraculum_media_2v2/jetson_clips/`.

## The machine

- `ssh jetson-spqr` from the laptop (192.168.0.152, user `jetsonspqr`, jump `orchestrator-droplet`).
- Jetson AGX Orin, JetPack 6 (L4T R36.4.3), Ubuntu 22.04 aarch64, 12 cores, 61 GB RAM, Docker 29.1.3 (API 1.52),
  default runtime `nvidia`. No sudo. Shared lab machine: all work is under `~/oraculum-sim-arm/` and in Docker.
- Not ours, do not touch: `~/spqr`, `~/spqr_sim` (a team tree from 2026-07), the image `spqr_maximus_bridge:latest`
  (arm64, 2026-08-06), two stopped containers `hardcore_carson`, `hungry_brown`. Our robot image has its own name.
- A user session runs on the physical display `:0`. We do not use it.
- Host tools: git, gcc 11, make, python 3.10, rsync, curl. No Xvfb, no pip, no system cmake
  (cmake 3.30.5 in `~/opt/cmake/bin`). Box64 v0.3.6 in `~/box64/build/box64`.

## Log

Times are wall-clock. "laptop" = this laptop, "server" = the x86 Hetzner server root@49.12.252.138 (read-only use),
"jetson" = the Jetson.

### 1. Docker bridge networks (jetson)

- `docker network create --subnet 172.29.0.0/16 oratest2 && docker run --rm --network oratest2 ros:humble true`
  FAILED: `iptables --wait -t raw -A PREROUTING -d 172.29.0.2 ! -i br-... -j DROP: can't initialize iptables table
  'raw'`. Docker 28+ adds a "direct access filtering" rule in the raw table for every container on a bridge.
- `docker network create -o com.docker.network.bridge.gateway_mode_ipv4=nat-unprotected --subnet 172.29.0.0/16 oratest`
  + the same `docker run`: WORKED. The `nat-unprotected` gateway mode skips the raw-table rule.
  circus creates `CIRCUS_network` itself (and fails if it exists), so the option is patched into circus's
  `include/CircusNetwork.h` (section 6).

### 2. Copy the private sources server -> jetson (laptop not in the data path)

- Path test (laptop): `ssh -A root@49.12.252.138 'O="-o BatchMode=yes -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile=/tmp/kh_jetson"; ssh $O -o ProxyCommand="ssh $O -W %h:%p root@142.93.104.36"
  jetsonspqr@192.168.0.152 hostname'`: WORKED. `ssh -J` FAILED (`Host key verification failed`): the jump
  process does not get the `-o` options; `ProxyCommand` does.
- Copy (laptop, 2026-10-22 16:4x): `ssh -A root@49.12.252.138 '... tar -C /workspace -cz --exclude=./build
  --exclude=./.pixi . | ssh $O -o ProxyCommand=... jetsonspqr@192.168.0.152 "mkdir -p ~/oraculum-sim-arm/workspace
  && tar -xz -C ~/oraculum-sim-arm/workspace"'`: WORKED, 464 MB in **28 s**. The copied tree already has the server's
  in-place edits: simbridge poll 200 us (`src/bridge_node.hpp` lines 98-99), `scenario: "sim_fast"`,
  `useRerun: true`, Rerun `mode: "save"` to `/dev/null`, `rgb: false`.

### 3. Versions (coordinator update 2026-10-22 ~16:50)

- circus **`31a7b67a`** ("camera info shm", branch `camera-info-fix`, 1 commit after 48154ea1), cloned on the jetson:
  `git clone https://github.com/SPQRTeam/circus.git ~/oraculum-sim-arm/circus && git checkout --detach 31a7b67a`
  (58 s, 382 MB).
- simbridge = the server's `ce708bfa` tree + the patch of **`625336d2`** ("camera info fix", same branch), applied on
  the jetson with `patch -p1 < ~/oraculum-sim-arm/patches/simbridge_625336d2.patch` (laptop fetched it:
  `gh api -H "Accept: application/vnd.github.patch" repos/SPQRTeam/simbridge/commits/625336d2`, 102 lines; copy in
  `/DATA/RoboCup/oraculum/hosted/jetson/simbridge_625336d2.patch`). circus and simbridge must match (shm layout).
- Robot framework = the server's `/workspace` (branch `feature/oraculum-tcm-mappazzone` + oraculum work, not a git tree).

### 4. pixi (jetson)

- `curl -fsSL https://pixi.sh/install.sh | PIXI_HOME=$HOME/oraculum-sim-arm/pixi PIXI_VERSION=v0.82.1
  PIXI_NO_PATH_UPDATE=1 bash`: WORKED, 8 s. pixi 0.82.1 (same as the server). Cache: `PIXI_CACHE_DIR=~/oraculum-sim-arm/cache/pixi`.

### 5. Box64 smoke test of booster-motion (jetson)

- `docker run --rm --network host --cap-add SYS_NICE --cap-add IPC_LOCK --ulimit rtprio=99 --ulimit memlock=-1
  -v ~/oraculum-sim-arm/box64:/usr/local/bin/box64:ro -v <simbridge>/tools/booster_motion:/opt/booster:ro -w /opt/booster
  -e BOX64_LD_LIBRARY_PATH=/opt/booster/lib:/opt/booster/lib-usr-local:/opt/booster/lib-x86_64-linux-gnu ros:humble
  timeout 25 box64 ./booster-motion -mode sim -config configs/config_isaac.lua`
  in bare `ros:humble`: the gait starts (`RsGaitApp.cpp:220 Gait start`, control thread priority 39 on processor 3),
  but `lib/libmodule_source.so` fails to load: Box64 wraps libXi, libXrandr, libdrm, libgbm, wayland, libxkbcommon,
  libdecor natively and the bare image lacks the arm64 versions. The robot image's apt list installs them.
- Box64 is called explicitly. Do not exec the x86 binary directly: the qemu binfmt (registered until reboot) would run
  it under QEMU, 25x slower.

### 6. circus (jetson, native, pixi)

- `bash ~/oraculum-sim-arm/patch_circus.sh` in `~/oraculum-sim-arm/circus` (script:
  `/DATA/RoboCup/oraculum/hosted/jetson/patch_circus.sh`): adds `linux-aarch64` to `pixi.toml` with gcc/gxx 14,
  `sysroot_linux-aarch64 >=2.34`, `libgl-devel`/`libegl-devel` 1.7.0; adds `gateway_mode_ipv4=nat-unprotected` to
  `include/CircusNetwork.h` (circus creates `CIRCUS_network` itself and fails if it exists, so a pre-created network
  does not help).
- Network test with circus's exact options (bridge name docker-circus, masquerade false, MTU 1500, iface prefix
  circus, nat-unprotected) + `--ip 172.21.1.11 --gpus all --privileged`: WORKED.
- `pixi install` 8 s (all packages resolved for linux-aarch64: Qt 6.9.2, MuJoCo 3.3.3, boost 1.88) +
  `rm -rf build && JOBS=10 pixi run compile`: WORKED. **Total 119 s.** `build/circus` is an aarch64 ELF.

### 7. Robot image (jetson)

- `docker build --network host -t oraculum-arm-base ~/oraculum-sim-arm/workspace` (the x86 Dockerfile unchanged,
  `FROM ros:humble` resolves to arm64; simbridge compiles natively): WORKED, **5 min 37 s**.
  `--network host` is needed: the default bridge fails (no raw table).
- Then `docker build --network host -t oraculum-arm-robot -f ctx/Dockerfile.robot ctx` (`ctx/` = Box64 binary +
  `/DATA/RoboCup/oraculum/hosted/jetson/Dockerfile.robot`). The first try died with its nohup'd parent shell; the
  rerun took 1 s. The image name is ours: `spqr_maximus_bridge:latest` on the jetson is the team's older image.
- Box64 test in the robot image: all X11/wayland libraries resolve; the only error was the arm64 `libSDL2-2.0.so.0`
  (Box64 wraps SDL2 natively). Fix: `libsdl2-2.0-0` in `Dockerfile.robot`.
- Box64 test with SDL2 added: no load errors; booster-motion runs until stopped. At SIGTERM it prints
  `pure virtual method called` (shutdown only).

### 8. Maximus (jetson, native aarch64, in a container)

- Why a container: the tree must be at `/workspace` (PROJECT_ROOT, pixi prefixes and RPATHs are absolute; the robot
  containers mount it there) and we have no sudo to create `/workspace` on the host.
- `bash ~/oraculum-sim-arm/patch_maximus.sh` in the workspace: adds `gcc_linux-aarch64`/`gxx_linux-aarch64` 14 and
  `sysroot_linux-aarch64 ==2.34` to `[target.linux-aarch64.dependencies]` (upstream has compilers only for linux-64,
  which cross-compiles for the robot).
- `bash ~/oraculum-sim-arm/build_maximus.sh` (`/DATA/RoboCup/oraculum/hosted/jetson/build_maximus.sh`): `ros:humble`
  container, our uid, `-v workspace:/workspace`, `pixi install` then `cmake -S /workspace -B /workspace/build/arm -G
  Ninja -DCMAKE_PREFIX_PATH=$CONDA_PREFIX -DENABLE_TENSORRT=OFF && cmake --build ... --parallel 10` (no toolchain file:
  `pixi run compile` uses `cmake/x86-toolchain.cmake`, which hard-codes the x86 compiler). WORKED: pixi install 14 s,
  **total 388 s**. Build type Debug `-O0` (the CMake default, same as x86). `ENABLE_TENSORRT` is unused by CMake.
  `onnxruntime-jetson` 1.20 comes with `libonnxruntime_providers_cuda.so` and `_tensorrt.so` (loaded at run time).
- `ldd` in the robot image: all libraries resolve (`libonnxruntime.so.1`, `libstdc++` from `/workspace/.pixi/envs/default/lib`).
- `scripts/supervisord.conf` of the jetson copy replaced by `/DATA/RoboCup/oraculum/hosted/jetson/supervisord.arm.conf`
  (x86 original kept as `supervisord.conf.x86`): booster-motion via `/usr/local/bin/box64`, Maximus =
  `/workspace/build/arm/src/app/maximus_main` without the x86 `ld-linux` wrapper.

### 9. Gateway, display, session scripts (jetson)

- Gateway: `/opt/oraculum` of the server copied server -> jetson (89 MB, 6 s) to `~/oraculum-sim-arm/oraculum`;
  host python 3.10 has pyyaml 5.4.1. Ports 8080, 10006, 3838, 6080, 5900 were free.
- Display image `oraculum-arm-display` (`Dockerfile.display`: ubuntu 22.04 + xvfb, x11vnc, novnc, websockify), built
  with `--network host`. Xvfb `:21` runs in it with `--network host`; circus on the host connects through the abstract
  X socket. Qt/xcb and llvmpipe work: the circus window opens.
- Scripts in `/DATA/RoboCup/oraculum/hosted/jetson/`, copied to `~/oraculum-sim-arm/`: `session.sh` (display, gateway +
  simulated referee, unpin loop through `docker exec`, circus `--no-images`), `measure_rtf.sh`, `cleanup.sh` (removes
  only `CIRCUS_` containers of our image; root-owned `/dev/shm/circus_ipc` removed from a container), `stop.sh`,
  `docker_config.yaml` (image `oraculum-arm-robot`), `scenes/1v0.yaml` (team 1), `1v1.yaml`, `2v2.yaml`.
  `hosted/vm/monitor_play.py` now reads the token file from `ORACULUM_TOKEN_FILE` (default unchanged).
- Trap: `pkill -f measure_rtf.sh` in an ssh command also kills the ssh command's own shell (its command line contains
  the pattern). `stop.sh` uses `[x]` patterns; run it in its own ssh call.

### 10. First 1-robot runs (jetson)

- Run 1 FAILED: circus `Waiting Robots are Ready...` forever. booster-motion died:
  `terminate called after throwing an instance of 'boost::interprocess::interprocess_exception' what(): Interprocess
  mutex timeout when locking`. Cause: FastDDS **data sharing** segments `/dev/shm/fast_datasharing_*` (boost
  interprocess mutex + segment manager) shared between booster-motion (x86 layout, Box64) and Maximus (arm64 layout;
  `pthread_mutex_t` is 40 vs 48 bytes).
- Run 2 FAILED the same way with a `fastdds_profile.xml` that sets `<data_sharing><kind>OFF</kind>` in default
  data_writer/data_reader profiles: both booster-motion and the booster SDK (Maximus) set their QoS in code, so XML
  defaults do not apply. (simbridge, ROS rmw, made no data-sharing segments.)
- Fix: `/DATA/RoboCup/oraculum/hosted/jetson/patch_fastrtps.py` binary-patches booster-motion's bundled x86
  `lib-usr-local/libfastrtps.so.2.13` (Apache-2.0 FastDDS, not the closed binary): `DataWriterImpl::` and
  `DataReaderImpl::check_datasharing_compatible` (offsets 0x436730, 0x47e430 from `nm -D`) become
  `out = false; return RETCODE_OK` (checked by disassembly: `this` in rdi, `bool&` in rdx, result in eax). The x86
  side then never offers data sharing, so every pair with booster-motion uses UDP loopback. `Dockerfile.robot` copies
  the patched library into the image.
- Run 3 WORKED: `Robot ready`, `Starting simulation!`; in PLAYING the robot walked 2.0-3.1 m per 10 s, joint range
  0.5-1.0 rad, no fall (monitor, 40 s). CPU in the container: booster-motion (Box64) 108-120 %, simbridge 42-46 %,
  Maximus 13-18 %. The RTF line was lost: `measure_rtf.sh` exited early under `set -e -o pipefail` (`top | head`
  SIGPIPE); fixed with `|| true`.

### 11. Results with Box64 (jetson, MODE_50W, CPU governor schedutil, max 1.4976 GHz; sim_fast, `--no-images`)

| Robots | Command | Wall | Real-time factor | Walk | CPU (top, %) |
|---|---|---|---|---|---|
| 1 (`scenes/1v0.yaml`) | `SCENE=~/oraculum-sim-arm/scenes/1v0.yaml SIM_S=60 ./measure_rtf.sh` | 103.4 s | **0.58** | 1.3-3.4 m per 10 s for ~50 s, then stands (joints 0.3 rad), no fall | circus 210, booster-motion (Box64) 172, Maximus 51, simbridge 49 |
| 2 (`scenes/1v1.yaml`) | `SCENE=~/oraculum-sim-arm/scenes/1v1.yaml SIM_S=60 ./measure_rtf.sh` | 167.4 s | **0.36** | 1.3 m in the first 10 s, then both stand (0.22 rad), no fall | circus 203, booster-motion 131 + 129, Maximus 43 + 43, simbridge 37 |

- The whole machine was 40-55 % idle: the limit is the lockstep latency per 2 ms substep (circus waits for every
  robot's command), not the core count. Box64 makes booster-motion's answer slower than on x86 (x86: 0.6-0.7 core).
- The stand-still after 10-50 s matches the x86 1v1 (joints settle at 0.21 rad from 20 s on, HETZNER.md).
- 4 "Timeout, resending state" lines in the 1v1 run (2 in the 1-robot run).

### 12. Network round trip for "robots on the Jetson, circus elsewhere" (jetson)

- `ping -c 20 -i 0.2` from the jetson: gateway 192.168.0.1 0.67 ms avg; lab hosts 192.168.0.206 0.85 ms,
  192.168.2.158 1.15 ms, 192.168.0.184 0.85 ms (max 2.7), 192.168.2.75 0.75 ms, 192.168.0.254 0.78 ms.
- circus waits for every robot's command after each 2 ms physics substep. A LAN round trip of 0.7-1.2 ms takes
  35-60 % of that budget before any compute, so the RTF of a split setup would be capped well below 1 unless the
  lockstep changes (e.g. robots answer once per 20 ms control step instead of per substep, or circus runs ahead).
- circus's socket mode (TCP msgpack) carries no camera images today, so `sim_real` (YOLO on the camera) cannot run
  split. Shared memory (`shm`) needs the same host. What a split needs: circus image transport over the network,
  a looser lockstep, and the 172.21.x.x robot network bridged or routed between the hosts.

### 13. Native aarch64 booster-motion from the T1 firmware (jetson, coordinator request 2026-10-22 ~17:20)

- Download on the jetson, one connection: `curl -fsSL -o ~/oraculum-sim-arm/dl/<name> <url>` ran at only 0.6 MB/s
  (estimate 90 min). Replaced by 16 parallel HTTP range requests:
  `~/oraculum-sim-arm/fetch_ranges.sh <url> <out> 3909080772 16` (`/DATA/RoboCup/oraculum/hosted/jetson/fetch_ranges.sh`):
  ~7 MB/s, done in **295 s**. File `1.8.0.9-release-02011-2026-09-14-global.22.04.aarch64-unsealed.single.run`,
  3909080772 bytes; payload MD5 = the header's `8aa12a778301db3fecfcc91a7e76581b`.
- It is a Makeself 2.4.5 archive (`skip=718` header lines, zstd tar, `script="./install.sh"`). Never run: unpacked
  with `tail -c 3909061785 <run> | zstd -cd | tar -x -C ~/oraculum-sim-arm/fw-1.8.0.9 --wildcards "./booster/bin/*"
  "./booster/lib/*" "./booster/Gait/*"` (29 s). Listing: `~/oraculum-sim-arm/logs/fw_list.txt` (3974 entries).
- `fw-1.8.0.9/booster/bin/booster-motion`: ELF aarch64, 80 MB; modules in `booster/lib/motion/` (1.9 GB with the RL
  models), other libraries in `booster/lib/` (2.3 GB), configs in `booster/Gait/configs/{T1,K1,T2,...}`. It needs
  `liblua5.3-c++.so.0` and `libglog.so.0` (added to `Dockerfile.robot`: `liblua5.3-0 libgoogle-glog0v5`).
- With the x86 sim package's configs (`configs/config_isaac.lua`, simulation package 0.0.11): FAILED,
  `module_scheduler.cpp:241 The following connections failed to connect: con_commander_manager_2_intercept_planner_idx`
  then `terminate called without an active exception` (old graph vs new modules).
- With the firmware's own `Gait/configs/T1/config.lua` (`is_real_bot = true` = the `rs_sdk_interface` graph, the same
  module the x86 sim graph uses) and `-mode sim` (`ISimTransport.cpp:18 Creating SimTransport: ROS/DDS topic`):
  it needs the robot's layout: cwd = a `bin/` folder with `lib/` = `booster/lib/motion` (it loads `lib/*.so`) and
  `../configs` = `Gait/configs` (it reads `../configs/T1/*.txt`); absolute `/opt/booster/Gait/configs/...` (urdf,
  toml); `/opt/booster/robot_info.txt` with a `Model Version:` line (else `config_utils.lua:49: attempt to index a nil
  value`). Layout on the jetson: `~/oraculum-sim-arm/booster-native/{bin/booster-motion, bin/lib, configs,
  robot_info.txt ("Model Version: 1.0.0"), fwlib/ (mount point)}`, mounted by `docker_config.native.yaml`;
  `supervisord.arm.conf` runs it when `/opt/booster-native/bin/booster-motion` exists, else Box64. It ignores SIGTERM
  (`stopwaitsecs=3`).
- 1 robot, native: circus reaches `Robot ready` and `Starting simulation!`; **RTF 0.81** (60 s in 74.3 s) and
  0.79 (30 s in 37.7 s); booster-motion 70 % CPU (Box64: 172 %). **But the robot is already FALLEN when PLAYING
  starts** (monitor every 2 s) and never gets up. So native is NOT usable yet.
- Tried: `simulator_out.is_real_bot_ = false` + `simulator_in.use_pvt_ = false` (the x86 sim values) in
  `common_module_options.lua`: booster-motion died (`RsGaitApp.cpp:54 [Duration timeout] name:t_recv_from_core
  time:1248.69`), circus waited forever. Reverted (`.orig` kept).
- Open: the firmware's robot config does not match circus/simbridge's simulated T1 (ankle parallel mechanism, PD
  gains, start mode). Needs Booster's matching simulation config for 1.8.x, or a mapping of the 0.0.11 isaac options
  onto the 1.8 module names. Box64 stays the default.
- **Update: solved by `config_sim_circus.lua` (decompile agent), see section 17**: the native robot walks and plays
  after a fall at the first PLAYING step.

### 14. GPU for Maximus's neural networks (sim_real, YOLO detector) (jetson)

- JetPack 6's container runtime mounts only the driver (`/etc/nvidia-container-runtime/host-files-for-container.d/`:
  `devices.csv`, `drivers.csv`). circus already asks Docker for the GPU per container (CDI `nvidia.com/gpu=all` is
  listed, so `hasNvidiaGPU()` is true): `/dev/nvgpu`, `nvhost-*` and `libcuda.so` are in the robot container.
- `onnxruntime-jetson` 1.20 needs `libcudart.so.12`, `libcublas(Lt).so.12`, `libcufft.so.11` (host
  `/usr/local/cuda-12.6`, `cuda-cudart-12-6 12.6.68`) and `libcudnn.so.9`, `libnvinfer.so.10`,
  `libnvinfer_plugin.so.10`, `libnvonnxparser.so.10` (host `/usr/lib/aarch64-linux-gnu`: cuDNN 9.3.0.75, TensorRT
  10.3.0.30). `cp -a /usr/lib/aarch64-linux-gnu/{libcudnn*,libnvinfer*,libnvonnxparser*}.so* ~/oraculum-sim-arm/gpulibs/`
  (1.4 GB, 2 s). `docker_config.gpu.yaml` mounts `/usr/local/cuda-12.6` and `gpulibs` at `/opt/gpulibs`.
- `patch_entrypoint.sh`: the jetson copy of `scripts/docker_entrypoint.sh` sets `LD_LIBRARY_PATH` to the GPU libraries
  and does NOT set `SPQR_NN_CPU` when `/opt/gpulibs` exists; else `SPQR_NN_CPU=1` as on x86.
- `measure_rtf.sh` takes `SCENARIO=sim_real` (edits `settings.yaml`, sets it back to `sim_fast` on exit) and
  `CIRCUS_IMAGES=1` (circus renders the robot cameras, llvmpipe).
- Run (1 robot, sim_real, GPU, Box64): `CIRCUS_IMAGES=1 SCENARIO=sim_real FRAMEWORK_CFG=docker_config.gpu.yaml
  SCENE=~/oraculum-sim-arm/scenes/1v0.yaml SIM_S=60 ./measure_rtf.sh`. Maximus log: `[NeuralNetwork] TensorRT
  execution provider requested`, `CUDA execution provider requested`; ORT loads `models/det/det_trt.onnx` (an
  EPContext model with an embedded TensorRT 10.3 engine) with the warning `Using an engine plan file across different
  models of devices` (engine built on the robot's Orin). **RTF 0.52** (60 s in 115 s). CPU: circus 217 %,
  booster-motion 95 %, **Maximus 83 %** (x86 CPU YOLO: about 330 % per robot), simbridge 50 %.
  The robot was reported FALLEN from the first 10 s of PLAYING (not seen in sim_fast with Box64); being checked.
- `patch_detector_timing.sh` (measurement only): `ObjectDetector.cpp` logs the inference time every 100 frames
  (`inference ms over N frames: mean/min/max`). Incremental Maximus rebuild: 106 s.
- Robot logs: circus removes the containers when it exits, so `measure_rtf.sh` now copies the last 2 MB of each
  robot log every 5 s to `~/oraculum-sim-arm/logs/robots/<container>/`.
- **Inference time of the YOLO detector (1 robot, sim_real, 60 s):**

| Run | Provider | Inference (ms) | Maximus CPU | RTF |
|---|---|---|---|---|
| GPU (`docker_config.gpu.yaml`) | TensorRT EP (`det_trt.onnx`, TRT 10.3) | mean 19.4, min 17, max 51 (2300 frames) | 71-144 % | 0.51 (run 3), 0.52 (run 1), 0.34 (run 2) |
| CPU (`docker_config.yaml`, `SPQR_NN_CPU=1`) | ONNX Runtime CPU (`det.onnx`) | mean 887, min 655, max 1272 (100 frames) | **716 %** | 0.28 (40 s in 143.7 s) |

- The robot falls in sim_real on GPU AND on CPU (`[FallDetector] IS_STANDING -> IS_FALLING (tilt=0.53 rad)` then
  `HAS_FALLEN`, within the first 10 s of PLAYING), and not in sim_fast. So the fall is not caused by the GPU. Not
  explained (sim_real behaviour or lower RTF). Run 2 had no fall and RTF 0.34: the RTF varies between runs.

### 15. More robots (jetson)

| Game | Scenario | booster-motion | Real-time factor | Notes |
|---|---|---|---|---|
| 2v2 (`scenes/2v2.yaml`) | sim_fast | Box64 | **0.16** (60 s in 364.4 s) | roles Goalie/Striker per team (team coordination works); 3 of 4 robots FALLEN from about 50-80 s of wall time; booster-motion 62 % x4, Maximus 38-44 % x4, circus 184 % |
| 1v1 (`scenes/1v1.yaml`) | sim_real, GPU | Box64 | **0.29** (60 s in 207.6 s) | YOLO 21.6 / 21.2 ms mean per robot (TensorRT); red falls at ~30 s; Maximus 99 % + 74 %, booster-motion 112 % x2 |

- During both runs another job of the same user account ran on the jetson: Ghidra (`java ... ghidra.GhidraClassLoader`,
  nice 19, 1-3 cores, plus `decompile`). Not ours, not touched. It lowers these numbers; the 1-robot numbers above were
  taken before it started.
- Robots fall when the RTF is far below 1 (booster-motion's controller runs on the wall clock), as on x86 (HETZNER.md).
- The unpin loop works under Box64: Box64 rewrites the process arguments to `/opt/booster/booster-motion -mode sim
  ...` (comm `booster-motion`), the `pgrep -f /opt/booster/booster-motion` pattern matches it, and during a 1v1 run all
  17 threads had `Cpus_allowed_list: 0-11` (the log still shows `running processor : 3` from before the unpin). So the
  2v2 number measures Box64, not the pinning. (The native booster-motion pins to cores 6/7 and its cmdline is
  `./booster-motion`: the loop does not match it; matters only once the native fall is fixed.)
- 1v1 sim_fast Box64 again, with the Ghidra job at about 4 cores (java 182 % + 104 % + 48 %, 3 x decompile 45 %):
  **0.29** (60 s in 205.7 s), versus 0.36 without it.
- sim_real with Box64 is NOT working as a game yet: the robot's self-localization never produces a pose (every
  GameController return message shows `pose 0/0/0`, monitor "walked 0.0 m"), and the robot falls on the GPU and on
  the CPU. (With the native booster-motion it localizes: see "Native sim_real with GPU" below.) What works: the YOLO detector on the GPU (19-21 ms vs 887 ms on the CPU).

### 16. Reproduction test of the build chain (laptop -> jetson, 2026-10-22 18:2x)

- Deleted on the jetson: `workspace/`, `circus/`, `ctx/`, `ctx-display/`, `box64` (kept: `cache/`, `pixi/`, `dl/`,
  `fw-1.8.0.9/`, `booster-native/`, `gpulibs/`, Docker images). Then on the laptop:
  `bash /DATA/RoboCup/oraculum/hosted/jetson/build_all.sh`. WORKED. `build_jetson.log`:
  `simbridge: 625336d2 already in` (the server tree has it now), `display_image: ok, 0 s` and `robot_image: ok, 2 s`
  (warm Docker cache), `circus: ok, 207 s` and `maximus: ok, 460 s` (cold compiles, in parallel),
  smoke test `simulated 30 s in 53.6 s of wall time: real-time factor 0.56`.

## Fall analysis (2026-10-22 evening, 1 robot unless noted)

Tools: `measure_rtf.sh` with `RUN_NAME=<name>` keeps each run's robot logs and monitor in
`~/oraculum-sim-arm/logs/falls/<name>/` and appends a line to `logs/falls/summary.txt` (falls = number of
`IS_STANDING -> IS_FALLING` in Maximus's log). `fall_runs.sh` runs the series. `fall_report.py <robot log folder>`
prints, from booster-motion's own log (it logs every `Move Command: vx, vy, vyaw` with a wall-clock timestamp), the
walk commands in the 3 s before booster-motion switched to Damping (Maximus sends mode 0 when its FallDetector fires).
`patch_fall_logging.sh` (Maximus `[MoveCmd]` log at 10 Hz) turned out not to be needed: booster-motion already logs
the commands. `patch_circus_ballpos.sh`: env `CIRCUS_BALL_POS="x y z"` places the ball (test only). `session.sh`:
env `CIRCUS_CPUS=<list>` pins circus with taskset.

### (A) Walk commands before the earlier falls (Box64; logs in `logs/before_rebuild/robots_*`)

| Run | Behaviour before the fall | Walk commands in the 3 s before (vx / vy / vyaw) | Last command |
|---|---|---|---|
| 1v0 sim_real GPU (run 3) | `[Striker] Search` (just entered), Brain out of cycle 31-44 ms (budget 20) | vx -1.07..0 (mean -0.93), vy -0.55..0.24 | (0, 0, 0) |
| 1v0 sim_real CPU | `[Striker] Search` | vx -1.11..0 (mean -0.57), vy 0..0.29 | (0, 0, 0) |
| 1v1 sim_real GPU red | `[Striker] Search` | vx -1.14..0 (mean -0.70), vy -0.51..0, vyaw -0.6..1.5 | (0, 0, 1.5) |
| 1v1 sim_real GPU blue | `[Striker] Search` | turn in place: vyaw -1.5..0 | (0, 0, -1.5) |
| 2v2 sim_fast red_0 (RTF 0.16) | - | vx -1.50..-0.66, vy -1.48..-0.73, vyaw 3.0 | (-1.45, -0.73, 3.0) |
| 2v2 sim_fast blue_0 | - | vx -0.71..0.62, vy -1.26..-0.33, vyaw 0.4..2.78 | (0.62, -0.50, 0.4) |
| 2v2 sim_fast blue_1 | - | constant (0.5, -0.3, -0.48) | (0.5, -0.3, -0.48) |
| 2v2 sim_fast red_1 | never fell | whole run max |vx| 0.50, |vy| 0.47, |vyaw| 1.5 | - |

- Every sim_real fall came right after the Striker entered Search, in 4 of 4 cases, after seconds of fast BACKWARD
  walking (vx about -1 m/s) or a fast turn in place (|vyaw| 1.5). Maximus sends commands up to |vx| 2.0, |vy| 2.0,
  |vyaw| 3.0 m/s, rad/s (the 0.0.11 sim config of booster-motion lists vel_x_max 1.2, vel_y_max 0.5, rotvel_max 1.5).
- In sim_real the self-localization pose stays 0/0/0 (section 15), so the Striker's walk targets are wrong.

### (B) Timing and (C) isolation runs (2026-10-22 18:35-18:48; `fall_runs.sh`; Box64; 1 robot; monitor every 1 s)

| Run | Scenario | Change | RTF | Falls | Walk commands (whole run max) |
|---|---|---|---|---|---|
| A1_simreal_gpu | sim_real, GPU | - | 0.46 | **0** | robot stayed in "Play ball", hardly walked |
| C1_simreal_gpu_noball | sim_real, GPU | ball at (0, 40, 0.11), off the field (`CIRCUS_BALL_POS`) | 0.45 | **0** | Search all run: turn in place only, |vyaw| <= 1.5, vx = vy = 0 |
| B0_simfast_control | sim_fast | - (90 s) | 0.56 | **0** | |vx| 1.46, |vy| 2.00, |vyaw| 3.00 |
| B1_simfast_circus1core | sim_fast | circus pinned to core 0 (`CIRCUS_CPUS=0`) | 0.56 | **0** | |vx| 1.56, |vy| 1.13, |vyaw| 3.00 |

- B1 did NOT slow the simulation: circus waits for the robot each substep and is not CPU-bound. The timing test needs
  another knob: `ROBOT_CPUS=<n>` (session.sh, `docker update --cpus` on each robot container) is written, not yet run
  (`fall_runs.sh B2`).
- Evidence so far: large commands alone (B0: up to |vy| 2.0, |vyaw| 3.0) do not make the robot fall at RTF 0.56;
  turning in place without a ball (C1) does not either. The 4 earlier sim_real falls came after seconds of fast
  backward walking (about -1 m/s) driven by a wrong self-pose (0/0/0); the 2v2 sim_fast falls came at RTF 0.16.
  No fall in these 4 runs. Earlier 1-robot sim_real runs: falls at RTF 0.52, 0.51 (GPU) and 0.28 (CPU), none at 0.34;
  so the RTF alone does not decide it in sim_real.

### 17. Native booster-motion with `config_sim_circus.lua` (decompile agent, `BOOSTER_MOTION_RE.md`) (jetson)

- `config_sim_circus.lua` (copied from `~/rea-work/booster-native-try/configs/T1/` to
  `~/oraculum-sim-arm/booster-native/configs/T1/`; copy in `/DATA/RoboCup/oraculum/hosted/jetson/booster-native/`):
  PD loop inside booster-motion (`pid::MITGroupController`), `simulator_in.use_pvt_ = false`,
  `simulator_out.is_real_bot = false`, serial-ankle bypass (`SIM_ANKLE_BYPASS`, default 1). `supervisord.arm.conf`
  runs the native binary with `${NATIVE_CONFIG:-config_sim_circus.lua}`, so in practice always
  `config_sim_circus.lua`: circus passes only a fixed list of environment variables to the robot containers, so
  neither `NATIVE_CONFIG` nor `SIM_ANKLE_BYPASS` can be set from the host. `SIM_ANKLE_BYPASS=0` was NOT run: the
  clips N1c, N3, N5 show normal walking and dribbling. A test would need a second config file (e.g.
  `config_sim_circus_nobypass.lua` with the bypass off) and a framework-config or supervisord variant that selects it.
- Clips exist only from 19:2x on (N1c and later). A1, C1, B0, B1 and every earlier run have no clip: recording did
  not exist yet.
- Clips: `measure_rtf.sh` records every run (ffmpeg x11grab in the display container, 10 fps, 960x540) to
  `~/oraculum-sim-arm/clips/<run>_<time>_wall.mp4` plus a real-speed copy `_realspeed.mp4` (sped up by 1/RTF);
  copies on the laptop in `/DATA/RoboCup/oraculum_media_2v2/jetson_clips/`. `ffmpeg` added to `Dockerfile.display`
  (rebuild 185 s). session.sh stops ffmpeg with SIGINT before it removes the display (a SIGKILLed ffmpeg left a
  36-byte file).

| Run | Config | RTF | Start | Afterwards | Clip |
|---|---|---|---|---|---|
| N1_native_simfast | native | 0.90 | FALLEN at PLAYING (tilt 1.55 rad), get-up done by ~7 s | Play ball / Search, walks, no further fall (55 s) | - |
| N1b (clip failed) | native | 0.78 | same | same | 36-byte file |
| N1c_native_simfast_clip | native | 0.76 | stands through INITIAL/READY/SET, falls on its back at the first step in PLAYING; up by ~14 s wall | walks to the ball and dribbles it towards the goal, no further fall | `N1c_native_simfast_clip_20261022_192530_{wall,realspeed}.mp4` |
| N2_native_simreal_gpu | native + GPU, sim_real | 0.28 | same start fall + get-up | YOLO 19.6 ms mean; little walking (localization) | - |
| N3_native_parity_simfast | native + firmware `system_settings_config.yaml`, `T1_2.3.4/robot_config.yaml`, Model Version 2.3.4 (`docker_config.native_parity.yaml`) | 0.74 | same start fall, get-up by ~8 s wall | walks 0.3-0.35 m/s, no further fall; "joint filter ... default settings" warning gone | `N3_native_parity_simfast_20261022_192945_*` |

- Native CPU: booster-motion 105 % (Box64: 172 % for 1 robot), circus 213 %, Maximus 46 %, simbridge 46 %.
- The start fall, from booster-motion's own log (N3): at start `Remote controller disabled, switch to damping mode`;
  Maximus's first `ChangeMode(1)` (Prepare in SDK 1.7.0) answers `Change mode: 1 , robot already in this mode`; at
  PLAYING `exec switch to BoosterAgent` (firmware 1.8 modes: Damping, Prepare, BoosterAgent, Custom, Robocup; its
  log says `wbcgait disable in booster agent mode`, `wbcgait enable in RobocupMode`). The fall comes at that switch.
  Likely cause: the SDK 1.7.0 mode numbers in Maximus do not match firmware 1.8's modes (no Prepare stand-up phase,
  and Maximus's "walking" lands in BoosterAgent, not Robocup). Not verified; the decompile agent can check the
  mode enum of 1.8 against `booster_robotics_sdk` 1.7.0.

### (B2) Timing test with a CPU cap on the robot container (Box64, sim_fast, 1 robot)

- `ROBOT_CPUS=0.6 ./fall_runs.sh B2` (`docker update --cpus 0.6` on the robot container): **RTF 0.10** (40 s in about
  400 s), **0 falls**; booster-motion 38 %, Maximus 19 %, simbridge 9 %. The robot stood and turned/walked slowly
  (max |vx| 0.74, |vy| 0.95, |vyaw| 2.45). Clip `B2_simfast_robot_cpus0.6_20261022_193620_*`.
- So a lone robot that mostly stands does not fall at RTF 0.10. Walking at a low RTF was NOT tested by this run.

### Native 1v1 detail (N4)

- The clip (`N4_native_1v1_simfast_20261022_193224_*`) shows both robots meeting at the ball at about 54-58 s wall
  and red going down in the contact; red does not get up again, blue keeps playing.

### Other checks

- IPC: circus sets no `IpcMode`, so each robot container has its own (private) SysV IPC. Box64 booster-motion prints
  `msgget: No such file or directory` once at start (B0); the native one does not. Private IPC keeps the robots'
  message queues apart, which `IpcMode: host` (circus branch `rviz2tf` 7e4dfbb8) would not. Not changed.

### Verdict (so far)

| Cause | Evidence | Verdict |
|---|---|---|
| Timing (RTF far below 1) | lone robot at RTF 0.10 (B2) and 0.45-0.56 (A1, C1, B0, B1): no fall; but in B2 and A1 the robot hardly walked (B2 max |vx| 0.74, 0.0 m per interval) | **not shown either way**: B2 is inconclusive (no walking at low RTF). Remaining evidence: the 2v2 at 0.16 fell (also contacts, fast commands) and HETZNER.md (x86 falls at low RTF) |
| Walk commands / behaviour | 4 of 4 sim_real falls (Box64) after seconds of fast backward walking (vx about -1 m/s) or fast turning, driven by a self-pose stuck at 0/0/0 (Box64 only; native localizes, N5); B0 shows large commands alone do not suffice | **main lead for sim_real with Box64**: no localization -> extreme commands; native sim_real (N5) did not fall after the start |
| Contacts (ball, other robot) | C1 without ball: no fall; N4 red fell in a robot-robot contact | contributes in games with several robots |
| Native start fall | every native run falls at the first PLAYING step, after `exec switch to BoosterAgent`; SDK 1.7.0 kWalking=2 / kPrepare=1 vs firmware 1.8 modes | **mode mapping** (decompile agent is checking the 1.8 enum) |

### Native sim_real with GPU, with clip (N5) and a correction about localization

- N5_native_simreal_gpu_clip (`docker_config.native_gpu.yaml`, sim_real, `CIRCUS_IMAGES=1`): **RTF 0.48**
  (60 s in 124.5 s; N2 had 0.28 with the Ghidra job running), YOLO 20.0 ms mean (TensorRT). Start fall + get-up
  by about 12 s wall, then it walks (up to 1.7 m in 2 s) with no further fall. Clip
  `N5_native_simreal_gpu_clip_20261022_194348_*`.
- **Correction:** `pose 0/0/0` in the GameController return message is what Maximus sends while fallen. With the
  NATIVE booster-motion the standing robot reports real poses (e.g. `671.943/1169.91/0.149`, mm). With the BOX64
  booster-motion (0.0.11 sim package) every sim_real run reports `fallen 0, pose 0/0/0` the whole time
  (1v0 GPU 116 of 116 messages, CPU 1222/1222, A1 1180/1180, C1 1247/1247). So in sim_real the self-localization
  works with native booster-motion and does not on the **Box64 path on the Jetson**. It is not a 0.0.11 problem in
  general: on the x86 server (same 0.0.11 booster-motion, native x86) the robots localized in sim_real PLAYING
  (coordinator, 2026-10-22 ~16:00 UTC).
- One log comparison, Maximus logs of A1 (Box64, sim_real GPU) vs N5 (native, sim_real GPU):

| Maximus log line | A1 Box64 | N5 native |
|---|---|---|
| `SAMPLE_LOST on topic: rt/odometer_state` (shows the topic arrives) | **0** | 42 |
| `RPC request timed out` (Maximus -> booster-motion RPC) | **9** | 0 |
| `TeamBallLocator TeamBall: (...)` (ball estimate) | **0** (3551 x `Balls not available`) | 4700 |
| camera `SAMPLE_LOST` rgb / depth | 206 / 159 | 767 / 505 |

  So on the Box64 path Maximus gets no `rt/odometer_state` from booster-motion (no odometry -> no self-pose -> no
  ball position on the field) and some RPC calls time out; camera frames do arrive. Suspects, not tested: the
  patched x86 FastDDS (`patch_fastrtps.py`, data sharing off) or the UDP-only profile dropping/delaying this
  topic, or the topic not being published under Box64 (Box64 prints `msgget: No such file or directory` once at
  start). This links the Box64 sim_real falls (fast backward walking from a wrong pose) to the Box64 path.

## Build chain (fastest known)

Run from the laptop: `bash /DATA/RoboCup/oraculum/hosted/jetson/build_all.sh`. The default (native booster-motion)
needs the T1 firmware: 3.9 GB download (about 5 min with 16 ranges) + about 50 s unpack on the first build;
`NATIVE=0` skips it (then only `BOOSTER_MOTION=box64` works). It does, in order:

1. laptop -> jetson: `scp` of the scripts in `/DATA/RoboCup/oraculum/hosted/jetson/` (+ `vm/monitor_play.py`,
   `scenes/`, `booster-native/config_sim_circus.lua`) to `~/oraculum-sim-arm/`.
2. server -> jetson (laptop not in the data path, `ssh -A` + `ProxyCommand` through the droplet): tar of the server's
   `/workspace` without `build/` and `.pixi/` (464 MB, **28 s cold**) and `/opt/oraculum` (89 MB, **6 s**).
3. jetson, `build_jetson.sh` (detached, log `~/oraculum-sim-arm/logs/build_jetson.log`):
   1. pixi 0.82.1 into `~/oraculum-sim-arm/pixi` (8 s); Box64 copied from `~/box64/build/box64` (a source build
      v0.3.6 is in the script, untested here);
   2. simbridge `625336d2` patch if missing; `patch_maximus.sh`, `patch_entrypoint.sh`, `patch_detector_timing.sh`;
      `supervisord.arm.conf` over `scripts/supervisord.conf`; `patch_fastrtps.py` -> `ctx/libfastrtps.so.2.13`;
      `workspace/.dockerignore` (`.pixi`, `build`, `models`);
   3. in parallel: circus `31a7b67a` clone + `patch_circus.sh` + `pixi install` + compile (**119 s cold** alone,
      207 s next to the Maximus build); robot image `oraculum-arm-base` (**5 min 37 s cold**) then
      `oraculum-arm-robot` (seconds); `build_maximus.sh` (**388 s cold** alone, 460 s next to circus); display image
      (`oraculum-arm-display`, with ffmpeg: **185 s cold**);
   4. `gpulibs/` (cuDNN 9.3 + TensorRT 10.3 copied from the host, 2 s);
   5. unless NATIVE=0: firmware download/unpack, `booster-native/` layout, `config_sim_circus.lua`;
   6. smoke test: 1 robot, 30 s, sim_fast, native booster-motion (Box64 with NATIVE=0), with a clip.
- Measured end to end (warm Docker cache, cold circus and Maximus compiles): **580 s** on the laptop clock,
  smoke test RTF 0.56. Cold Docker as well: about 8-9 min (estimate, not measured; the base image is the longest step).
- Tested chain = the 18:2x reproduction test (section 16). Changed after it: clips (ffmpeg in `Dockerfile.display`,
  `session.sh`, `measure_rtf.sh`), `RUN_NAME`/`CIRCUS_CPUS`/`ROBOT_CPUS`, `supervisord.arm.conf` (native config),
  `patch_circus_ballpos.sh` + `patch_fall_logging.sh` in `build_jetson.sh`, the NATIVE block (configs extraction,
  `config_sim_circus.lua`). `build_jetson.sh` was rerun on the jetson after these changes (result below); the NATIVE
  block and `build_all.sh`'s new copy line are written, not run end to end.
- Run: `SCENE=~/oraculum-sim-arm/scenes/<1v0|1v1|2v2>.yaml SIM_S=60 ~/oraculum-sim-arm/measure_rtf.sh` (native
  booster-motion), with `BOOSTER_MOTION=box64` for the Box64 path, `GPU=1` for the GPU, or
  `FRAMEWORK_CFG=docker_config.native_parity.yaml`; `SCENARIO=sim_real CIRCUS_IMAGES=1` for perception;
  `RUN_NAME=<name>` keeps logs in `logs/falls/<name>/`. Every run records a clip in `clips/`.
  A session to watch: `SCENE=... ~/oraculum-sim-arm/session.sh`, then
  `ssh -L 8080:localhost:8080 -L 6080:localhost:6080 jetson-spqr` and the token in `~/oraculum-sim-arm/run/token`.
  Stop everything: `~/oraculum-sim-arm/stop.sh` (in its own ssh call).

## Left on the Jetson (2026-10-22 19:50)

- Nothing running of ours: no `CIRCUS_` containers, no `CIRCUS_network`, no `oraculum-arm-display`, no circus /
  gateway / ffmpeg processes, no `/dev/shm/circus_ipc`, ports 8080/6080/5921 free (checked after `stop.sh`).
- Files: `~/oraculum-sim-arm/` 23 GB (`workspace` 6.0 GB incl. Maximus `.pixi` + `build`, `dl` 3.7 GB = the firmware
  `.run`, `fw-1.8.0.9` 3.5 GB, `circus` 2.9 GB, `cache` 2.4 GB, `booster-native` 2.3 GB, `gpulibs` 1.4 GB, `clips`
  25 MB). The firmware `.run` can be deleted (`dl/`) once the unpack is no longer needed.
- Docker images: `oraculum-arm-base` (2.18 GB), `oraculum-arm-robot` (2.29 GB), `oraculum-arm-display` (861 MB),
  plus untagged older layers of these from rebuilds (not pruned: `docker image prune` would also touch other users'
  images).
- Robot code edits in the jetson copy only (measurement): `ObjectDetector.cpp` logs the inference time every 100
  frames (`patch_detector_timing.sh`); `BoosterRobotPortal.cpp` logs `[MoveCmd]` at 10 Hz (`patch_fall_logging.sh`).
  circus copy: `CIRCUS_BALL_POS` override (`patch_circus_ballpos.sh`, default unchanged).
- Not ours, untouched: `~/spqr`, `~/spqr_sim`, `spqr_maximus_bridge:latest`, containers `hardcore_carson`,
  `hungry_brown`, the Ghidra/`rea` jobs of the decompile agent (`~/rea-work`).
- Limits only the owner can change (sudo): power mode `MODE_50W` (CPU max 1.4976 GHz; MAXN would allow about
  2.2 GHz), Docker's iptables raw-table problem (worked around with `nat-unprotected`).
- On the x86 server: only `/tmp/kh_jetson` (known-hosts file for the server -> jetson copy) was written.

## Open problems

1. ~~Start fall of the native path~~: fixed by `SPQR_SIM_FW18` + simbridge waiting for Prepare (last section). The
   Maximus change is uncommitted in `/home/xps/work/spqr-merge`; the team must decide whether to commit it.
2. Box64 path on the Jetson, sim_real: no `rt/odometer_state` reaches Maximus, so the self-pose stays 0/0/0; the
   Striker then walks fast backwards and falls. (Native and x86 localize.)
3. RTF with 2+ robots: 1v1 0.36 (Box64 and native alike), 2v2 0.16 (Box64): the per-substep lockstep, not CPU, is
   the limit (machine 40-60 % idle). circus is not CPU-bound (pinning it to 1 core changed nothing).
4. Split setup (robots on the Jetson, circus elsewhere): LAN RTT 0.7-1.2 ms vs a 2 ms substep, and socket mode has no
   camera images (section 12).
5. The Maximus build is Debug `-O0` (as on x86): `Brain out of cycle: took 31-44 ms, budget was 20 ms` in sim_real.
   A Release build was not tried.

## After the switch to native as default (2026-10-22 ~19:55)

- `build_jetson.sh` rerun on the jetson after the post-18:2x script changes (before the switch): WORKED,
  `maximus: ok, 52 s` (incremental), `circus: ok, 114 s` (with `patch_circus_ballpos.sh`), images warm, smoke test
  (Box64 at that time) RTF 0.47, clip `rtf_20261022_195336_*`.
- Smoke test of the new default (`session.sh` picks `docker_config.yaml` = native): `RUN_NAME=S1_default_native_smoke
  SCENE=~/oraculum-sim-arm/scenes/1v0.yaml SIM_S=30 ./measure_rtf.sh`: `framework config: docker_config.yaml`,
  **RTF 0.81**, start fall at PLAYING, up by ~10 s, then walks 0.3-0.4 m/s. Clip `S1_default_native_smoke_20261022_195626_*`.
- Not run after the switch: `build_jetson.sh` / `build_all.sh` end to end with the native default (the NATIVE block
  is written, its pieces were run by hand).

## Start-fall fix: SPQR_SIM_FW18 (2026-10-22 ~20:10; `BOOSTER_MOTION_RE.md` section 11)

Cause (decompile agent): booster-motion 1.8 maps SDK `kWalking` (2) to BoosterAgentMode and `kSoccer` (4) to
RobocupMode (what real robots use), and it boots in damping. Maximus used `kWalking` in simulation (written for the
0.0.11 package) and never sent Prepare.

- Code change, **uncommitted** in `/home/xps/work/spqr-merge` (no git add, no commit) and applied to the jetson tree;
  diff `/DATA/RoboCup/oraculum/hosted/jetson/maximus_sim_fw18.patch` (applied by `build_jetson.sh`):
  - `src/app/nodes/brain/rl/BoosterController.cpp`: `simFirmware18()` = env `SPQR_SIM_FW18` set;
    `runningMode()` gives `kSoccer` when it is set (else unchanged: sim `kWalking`, real `kSoccer`); `update()` sends
    `ChangeMode(kPrepare)` once at boot when it is set, retried every 500 ms until booster-motion answers.
  - `src/app/nodes/brain/behaviors/states/Fallen.cpp`: the get-up mode follows the same rule.
  - Box64/0.0.11 path and real robots: unchanged (the variable is not set there).
- `supervisord.arm.conf`: sets `SPQR_SIM_FW18=1` for Maximus only when the native booster-motion is mounted.
- First build failed (`'simFirmware18' was not declared in this scope`: defined below its first use); fixed. The
  failed build still printed `rc=0`: `build_maximus.sh` now runs its container script with `set -e`.

| Run | Change | RTF | Boot | First PLAYING step | Falls | Clip |
|---|---|---|---|---|---|---|
| F1_fw18_native_simfast | kSoccer + boot Prepare | 0.75 | lying on its back in the first frame: physics starts while booster-motion is still in damping; Prepare comes too late, FallDetector (tilt 1.55) sends damping, get-up into Robocup by ~12 s | `Change mode: 4, robot already in this mode`, no fall | 1 (boot) | `F1_fw18_native_simfast_*` |
| F2_fw18_prepwait_simfast | + simbridge waits for `exec switch to prepare` | 0.69 | stands from the start (`exec switch to prepare`, then `exec switch to Robocup`) | no fall | **0** | `F2_fw18_prepwait_simfast_*` |
| F3_fw18_1v1_simfast | same, 1v1 | **0.40** | both stand | no fall | **0** in 150 s wall | `F3_fw18_1v1_simfast_*` |
| F4_fw18_simreal_gpu | sim_real + GPU, Debug Maximus | 0.45 | stands | no fall | **0**; localizes (1252 real poses); YOLO 20.0 ms | `F4_fw18_simreal_gpu_*` |
| F5_fw18_simreal_gpu_release | sim_real + GPU, **Release** Maximus | **0.65** | stands | no fall | **0**; localizes (841 real poses); YOLO 14.2 ms | `F5_fw18_simreal_gpu_release_*` |

- Why the wait works (user, confirmed in circus `src/RobotManager.cpp` 123-126 shm / 209-211 socket): circus marks a
  robot ready on its FIRST command message, whatever it holds, and only then steps the physics. booster-motion 1.8 in
  damping sends zero-torque commands at once; 0.0.11 started in a holding posture. Chosen option (B), in
  `supervisord.arm.conf`, native path only: simbridge starts after booster-motion's log shows `exec switch to
  prepare` (max 30 s). Maximus's Prepare goes over RPC and needs no simulation data. Option (A) (simbridge drops
  near-zero-torque commands, circus branch `rviz2tf` 7e4dfbb8) was not needed.
- Walking speed (monitor, intervals with >= 0.1 m moved, converted to simulated time): BoosterAgentMode N1c 0.29,
  N3 0.31, S1 0.39 m/s; RobocupMode F2 0.25 (1 s intervals), F3 0.33 m/s (max 0.94). Not clearly slower; no lead
  for the ankle Jacobian from this. (Estimate from the self-pose reported to the gateway, not a straight-line test.)

### Debug vs Release Maximus (sim_real, GPU, native, 1 robot)

- Release build: `BUILD_TYPE=Release bash ~/oraculum-sim-arm/build_maximus.sh` -> `workspace/build/arm-release`
  (cold **425 s**). The file `workspace/build/USE_RELEASE` makes `supervisord.arm.conf` start the Release binary;
  without it the Debug build in `build/arm` runs (as on x86). **The file is in place now**, so the Jetson runs Release.
  `build_jetson.sh` still builds only Debug.

| | Debug (F4) | Release (F5) |
|---|---|---|
| RTF | 0.45 | **0.65** |
| Maximus CPU | 156 % | 60 % |
| `Brain out of cycle` lines (60 s simulated) | 248, mean 47.5 ms (budget 20) | 8, mean 72.5 ms |
| YOLO inference mean | 20.0 ms | 14.2 ms |
| Falls | 0 | 0 |

## Certification of `/home/xps/work/spqr-merge` @ 7fb7df9f (2026-10-23 ~16:00, before the real-robot test)

Tree: branch `feature/oraculum-tcm-mappazzone` @ 7fb7df9f (oraculum work + SPQR_SIM_FW18 + sim MANUAL in `Root.cpp` /
`LowControlBridge.h` + robot model in telemetry + merge of GitHub `RCAP2026-DEV` db0693a9). Nothing committed or pushed.

| Step | Result | Evidence |
|---|---|---|
| 1 sync | PASS | `rsync -a --exclude=.pixi --exclude=/build --exclude=.git ... /home/xps/work/spqr-merge/ jetson-spqr:~/oraculum-sim-arm/workspace/`: 21 files, 53 KB, 4 s. The measurement patches (ObjectDetector timing, `[MoveCmd]`) are overwritten by the tree; `maximus_sim_fw18.patch` NOT applied (the tree has the change). Jetson sim settings re-applied with `prepare_sim_config.sh` (new: pixi aarch64 compilers, GPU-optional entrypoint, arm supervisord, sim_fast, useRerun true, Rerun to /dev/null, rgb false) |
| 2 build | PASS | Release: 42/42 steps, 294 s, 0 errors, 0 warnings (except `-Wpsabi`). Debug: 42/42, 245 s, 0 errors, 0 warnings. The Jetson runs Release (`build/USE_RELEASE`) |
| 3 play | PASS | CERT1 (1 robot, sim_fast, native, RTF 0.83): 20 s of PLAYING, walked 6.4 m, 0/40 fallen samples, team 1, red, Striker |
| 4 MANUAL | **FAIL** | CERT2 (game held in INITIAL, RTF 0.82): 59/59 `/control` 200, Maximus enters Manual, robot moved 0.00 m in 6 s at vx 0.3. With `customMode: false` (deploy.yaml) `Manual.cpp` only requests `MotionState::Manual` ("body to firmware/RC"); the oraculum sticks never become `Move()`. Only the custom-mode branch calls `Walk()` |
| 5 STOP + RESUME | **FAIL (sim)** | STOP -> `ChangeMode(kPrepare)` -> booster-motion `exec switch to prepare` -> robot falls: standing in INITIAL (first fallen sample 1.0 s after STOP) and walking in PLAYING (1.5 s); also in CERT1. RESUME accepted, robot gets up via Fallen and plays. Likely our sim config (`config_sim_circus.lua`, ankle bypass) in PrepareBodyControl: the simulated robot never stood in Prepare before (at boot Robocup follows within 1 ms). Not evidence for real robots |

- Test scripts: `/DATA/RoboCup/oraculum/hosted/jetson/cert_test.py` (during PLAYING), `cert_test2.py` (INITIAL first;
  `measure_rtf.sh` with `GC_STATES=""`). Clips: `CERT1_7fb7df9f_release_20261023_160041_*`,
  `CERT2_7fb7df9f_release_20261023_160547_*` in `/DATA/RoboCup/oraculum_media_2v2/jetson_clips/`.

### Re-certification of MANUAL (7fb7df9f + uncommitted `Manual.cpp`, `Root.cpp`; 2026-10-23 ~16:55)

- Change: `Manual.cpp` streams the oraculum sticks as `Walk()` also with `customMode: false` while
  `oraculumManualActive()`; `Root.cpp` enters Manual on an active oraculum MANUAL on real robots too.
- Sync: rsync (2 source files + Jetson files rewritten by `prepare_sim_config.sh`). Release build incremental: 6 steps,
  80 s, 0 errors, 0 warnings. Test: `cert_test3.py` with `measure_rtf.sh GC_STATES=""`, RTF 0.80, clip
  `CERT3_manual_release_20261023_165333_*`.

| Step | Result | Numbers |
|---|---|---|
| 3 MANUAL from INITIAL | **PASS** | standing before (0.00 m in 3 s); vx 0.3 for 6 s: **2.59 m forward**, 0.04 m sideways; vtheta 0.5 for 4 s: **heading +24.8 deg**; vy 0.3 for 4 s: **0.60 m sideways**; after release back to autonomous standing (0.03 m in 5 s); 0 falls; 137/137 `/control` 200 |
| 4 MANUAL during PLAYING (testingOverride) | **PASS** | autonomous before: 3.3 m in 10 s; vtheta 0.5 for 4 s: **heading +95.8 deg**, 0.13 m forward; vx 0.3 for 5 s: **1.61 m forward**, heading +1.2 deg; after release autonomous play again (2.4 m in 12 s); 0 falls |

## GET UP / SIT / GO TO (robot commits 04ef450e + bc462d43 on top of e7ce3008; 2026-10-23 ~17:30-18:55)

Robot tree `/home/xps/work/spqr-merge`, branch `feature/oraculum-tcm-mappazzone`, local commits **04ef450e** and **bc462d43** (the remote's Prep combo also ends GET UP / GO TO; not pushed):
`LowControlBridge` reads `getup`, `goto {x, y, theta}`, `gotoCancel` and `sit`; Root states `getting_up` and
`go_to_pose`; telemetry latch `getup` / `goto` and `goto {x, y, theta}`. SIT: user decision "sit exists only for the
T2"; booster_robotics_sdk 1.7.0 has no sit call for any model, so the robot logs and ignores it, and the gateway answers
409 for a robot that is not a T2. Gateway (`src/control_server.py`, `src/socket_client.py`, `src/oraculum_cli.py`,
`config/positions.yaml`) copied to `~/oraculum-sim-arm/oraculum/` (old files in `oraculum/bak_goto/`); the Jetson's
`oraculum/config.yaml` field changed from `fieldAdultSize.yaml` to `fieldRCAP.yaml` (22 x 14 m = the simulation's fieldIO),
because `/goto` refuses targets off the field.

- Sync: `rsync` of the tree (same excludes as the certification) + `prepare_sim_config.sh`; then only `src/app/`.
  Release build incremental: first try failed (a missing `;` in `DebugMessageSender.cpp`); second 41/42 steps, 242 s,
  0 errors, 0 warnings; bc462d43: 5 steps, 45 s, 0 errors, 0 warnings. The 6 changed files on the Jetson = bc462d43 (md5).
- Test: `hosted/jetson/goto_test.py` with `GC_STATES="" RUN_NAME=GOTO4 SCENE=scenes/1v0.yaml SIM_S=330 ./measure_rtf.sh`
  (1 T1 robot, red, sim_fast, native booster-motion, Release Maximus @ bc462d43), **RTF 0.86**; GOTO3 = 04ef450e, RTF 0.83. Poses = the robot's self-pose in
  `/state`; in sim_fast that is circus's ground truth (OracleBridge). Times are wall time; simulated = wall x RTF.
  Self-check of the gateway rules and the CLI: `python3 tools/test_goto.py` (in-process, PASS).

| Step (GOTO4, bc462d43) | Result | Numbers |
|---|---|---|
| A GET UP on a standing robot (INITIAL) | **PASS** | HTTP 200, latch `getup`, moved 0.01 m in 6 s, 0 falls |
| B SIT on a T1 | **PASS** (409 as decided) | HTTP 409 "Sit exists only on the T2.", robot unchanged |
| C LIE DOWN, then GET UP | **N/A in simulation** | the simulated booster-motion answers `LieDown` with **501** (`Lie down requested, LieDown returned 501` in maximus.log): the robot never lies down; the GET UP that follows is a standing GET UP (200, latch `getup`). Not evidence for real robots |
| D DAMP → STOP → GET UP | **PASS** | DAMP 200, fallen after 1.0 s; GET UP while damped **409**; STOP 200 (latch `stop`); GET UP 200 → `GetUpWithMode(4) accepted`, standing after **13.1 s wall (11.3 s sim)** (GOTO3 17.6, GOTO2 15.6, GOTO1 10.1 s); then 6 s: 0 falls, 0.18 m moved, latch `getup` |
| E GO TO `ready_1` (-10.5, 0, 0) | **PASS** | 8.3 m; inside 0.3 m / 30 deg after **26.7 s wall (23.0 s sim)**; final error **0.248 m** (dx +0.229, dy -0.095), heading **-13.1 deg**; still (0.02 m in 3 s); 0 falls; telemetry `goto` = target. GOTO3: 20.7 s, 0.300 m, -13.9 deg; GOTO2: 22.7 s, 0.243 m, -12.9 deg |
| F GO TO `sideline_2` (-7.5, -7.0, 1.571) | **PASS** | 7.4 m; arrived after **15.6 s wall (13.4 s sim)**; final error **0.233 m** (dx +0.013, dy +0.233), heading **-14.4 deg**; 0 falls. GOTO3: 15.6 s, 0.228 m, -14.8 deg; GOTO2: 16.1 s, 0.275 m, -14.4 deg (that run's FAIL was the test reading the previous target from telemetry; fixed in the test) |
| G GO TO + cancel after 6 s | **PASS** | walked 3.21 m in 6 s; cancel 200 → stands (0.04 m in the last 3 s), latch `getup`, `goto` null |
| H Resume → autonomous | **PASS** | Resume 200, latch `""` after 0.5 s; READY/SET/PLAYING: walked 7.8 m in 15 s, 0 falls |
| I HTTP codes (game PLAYING) | **PASS** | GET UP / GO TO without override **403**; other client **423** (both); match robot (fake telemetry-only sender 127.0.0.2) **409** for getup, sit, goto; bad `pos` **400**; GET UP with `testingOverride` **200** (latch `getup`), then Resume 200 and play again (1.9 m in 8 s) |

- **Field mismatch in this simulation (seen in the clip, not a GO TO fault):** circus builds `fieldLarge` (14 x 9 m,
  `sim/simulation_configs/default.yaml`), while Maximus loads `fieldIO` (22 x 14 m) and the positions are RCAP (22 x 14 m).
  The robot reached the commanded coordinates (ground truth), but in circus `ready_1` (-10.5, 0) lies 3.5 m behind the
  14 m field's goal line (the clip shows the robot walking through the left goal and out of view), and `sideline_2`
  (y -7.0) 2.5 m outside the 9 m touch line. On the RCAP field (real robots, `fieldRCAP`) both are the intended spots.
  To test them inside the circus field, run circus with `field: fieldRCAP`.
- Arrival tolerance = the planner's `arriveXY` 0.3 m and `arriveTheta` 0.52 rad (30 deg, `planner.yaml`); the
  final heading error (13-15 deg) is inside it. A tighter heading would need `WalkToPose` `arriveThetaOverride`.
- Not tested in simulation: the remote's Prep combo during GO TO (bc462d43); a Prep drops the simulated robot
  (certification step 5).
- Clips (copied to `/DATA/RoboCup/oraculum_media_2v2/jetson_clips/`): `GOTO4_20261023_184753_{wall,realspeed}.mp4`
  (the table), `GOTO3_20261023_182924_{wall,realspeed}.mp4`, `GOTO2_20261023_180932_{wall,realspeed}.mp4`, `GOTO1_20261023_180455_wall.mp4` (stopped after step D:
  the test's `/positions` query was malformed). Test logs: `~/oraculum-sim-arm/logs/goto{1,2,3,4}_test.log`.
