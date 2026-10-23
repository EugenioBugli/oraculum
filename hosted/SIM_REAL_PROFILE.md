# Profile of the hosted 2v2 in scenario sim_real (2026-10-22)

Server: Hetzner CPX62 `49.12.252.138` (16 shared AMD vCPU, 32 GB, no GPU). Session: systemd `oraculum-sim`, scene
`/opt/session/2v2.yaml`, `CIRCUS_IMAGES=1`, circus `/opt/circus` commit 31a7b67a, shared-memory mode.
Robot code in the containers = `/home/xps/work/spqr-merge` (branch `feature/oraculum-tcm-mappazzone`, cea0ea87;
`NeuralNetwork.cpp` is byte-identical). All line numbers below refer to that tree or to `/opt/circus` on the server.
Method: read-only (`top`, `vmstat`, `pidstat -t`, `/proc/<pid>/task/<tid>/schedstat`, `perf record`, container logs).
Nothing was changed, restarted or stopped. The perf data files and one helper script in `/tmp` were removed afterwards.

Labels: **[M]** measured on the live session, **[E]** estimated (calculation from measured numbers), **[S]** read from source.

## Result

The ONNX Runtime thread pools spin. They are the cause of the slow simulation.

- Each Maximus process has a pool of 16 threads (15 workers + the Perception thread). The pool size comes from the
  default `Ort::SessionOptions` (one thread per vCPU), and spin-wait is on by default. **[M][S]**
- The four pools use 73 % of all CPU time on the server only for spin-wait (`ThreadPoolTempl::WorkerLoop`).
  The real YOLO work is 6.7 %. **[M]**
- The load average is 80 on 16 vCPU. 75-85 threads are runnable. Idle CPU is 0 %. **[M]**
- The lockstep relay (the simbridge main thread) waits 70 % of the wall time for a CPU. It runs 7.5 %. **[M]**
- A second cost is in the lockstep path itself: the circus physics thread copies about 4.6 MB of images per robot per
  control step (20 ms simulated). That takes about 6 ms of wall time per control step; at real time it would be up to
  about 30 % of the 20 ms budget. **[E]**

## 1. Maximus

| Item | Value | Label |
|---|---|---|
| CPU per Maximus process | 310-345 % | M |
| Threads per process | 137 (64 named `ld-linux-x86-64`, 69 FastDDS `dds.*`, 4 Rerun/jemalloc) | M |
| Busy threads | 16 threads at 15-31 % each; each waits 63-83 % of the time in the run queue | M (`pidstat -t`) |
| What the busy threads run (perf, one process, 5 s) | 81.2 % `WorkerLoop` (spin), 1.1 % `RunInParallel`, about 7 % real kernels (`MlasConvNchwcFloatKernelAvx512F` 3.9 %, `MlasConvPointwise…` 1.2 %, reorder, QuickGelu) | M |
| Thread 134791 | the Perception node thread (`ThreadRunner::threadMain` → `RunInParallel`, 54 % spin) | M |
| Threads 134784-134798 | 15 threads = the 15 nodes of `sim_real.yaml`; 134791 is Perception, the other 14 use 0.2-1.4 % each | E |
| ONNX Runtime version | 1.20.1, conda-forge CUDA build; `SPQR_NN_CPU=1` forces the CPU path | M |
| Intra-op threads | 16 (default 0 = one per core); inter-op: none (sequential mode) | M + S |
| Thread knob in the code | none. `make_options()` returns a default `Ort::SessionOptions` on the CPU path (`src/app/utils/nn/NeuralNetwork.cpp:34-35`). ONNX Runtime reads no environment variable for its pool size. | S |
| Model | `/workspace/models/det/det.onnx`, input `[1,3,640,640]`, output `[1,13,8400]` (9 classes), 233 nodes, 64 Conv, 44.7 MB fp32 (YOLOv8s size) | M |
| Perception cycle time | mean 1102-1184 ms, max 1419-1519 ms, budget 33 ms (per robot, from `ThreadRunner` "out of cycle" warnings) | M |
| Detection rate | 0.80 inferences/s per robot (48 in 60 s; 416 in 510 s) | M |
| Inference time | not logged: `Timer inferenceTimer_{"engine"}` (`ObjectDetector.h:35`) collects statistics but nothing prints them. The Perception cycle time above is the best measured proxy. | M |
| CPU work of one inference | about 0.3 core-seconds (0.26 core of kernels per robot ÷ 0.8 inferences/s); range 0.2-0.4 | E |
| Camera frames | circus publishes one RGB + one depth frame per control step = 50 per simulated second = about 11.5/s wall at RTF 0.23. Maximus logs SAMPLE_LOST for 8.6 RGB/s and 8.0 depth/s (robot red_0, 60 s). So about 3 frames/s arrive. The Bridge finds no RGB/depth/head-pose triple in 26 of its 30 cycles per second. | M (lost, cycles) + E (arrived) |

Four processes × 16 spinning threads = 64 threads on 16 vCPU. The spin keeps the inference slow (1.1 s instead of the
estimated 0.15-0.3 s), and a slow inference keeps the pool always active, so the spin never stops.

## 2. circus

| Thread | CPU | Run-queue wait | What it does | Label |
|---|---|---|---|---|
| main (Qt GUI, `paintGL`) | 37 % | 21 % | window render 1600x900 + 4 × (RGB + depth) offscreen render | M |
| llvmpipe-0, llvmpipe-1 | 30-32 % each | 27-31 % | Mesa software rasteriser, `LP_NUM_THREADS=2` | M |
| spqr::Simulation (physics + lockstep) | 12-14 % | 14-16 % | see below | M |
| total | 112 % | | | M |

- Rendering (main + llvmpipe) is about 97 of the 112 %. Physics is 12-14 %. **[M]**
- Camera resolution: 1280x720 for RGB and depth (`/opt/circus/resources/robots/Booster-T1/instance.xml:42,44`). **[S]**
- The scene sets no `offwidth`/`offheight`, so the MuJoCo default offscreen buffer is 640x480. `CameraRGB::render()` renders
  640x360 into it and scales the result up to 1280x720 with `Qt::SmoothTransformation`. The 1280x720 image holds no more
  detail than 640x360. YOLO then scales it down to 640x360 inside its 640x640 letterbox. **[S]**
- Render rate: the GUI timer is 16 ms (`/opt/circus/src/SimulationViewport.cpp:17`). Each paint renders every robot
  camera (`SimulationViewport.cpp:52-62`). The real paint rate under this load was not measured. **[S]**
- `--no-images` does NOT stop the camera rendering. It only stops the copy to shared memory
  (`/opt/circus/src/SimulationThread.cpp:104`). So sim_fast pays the same llvmpipe cost. This fits the 1.6 cores of
  circus in the sim_fast 1v1 in `HETZNER.md`. **[S]** (not measured in sim_fast today)
- Physics thread time split (perf, 8 s): `BoosterT1::sendMessageSHM` self 25.6 % + `memmove` 20.4 % + `memset` 4.3 % =
  about 50 % image copy; MuJoCo (`mju_dot`, `mju_addToScl`, `mju_chol*`, `mj_collideOBB`, …) about 20 %; the rest is the
  wait for the robots' commands. **[M]**
- Per control step (20 ms simulated, about 87 ms wall at RTF 0.23): the physics thread runs about 12 ms; about 6 ms of it
  is image copying (`getImage()` copy, depth to uint16, `memcpy` into `imageBuffer_`, write into the segment;
  `/opt/circus/include/robots/BoosterT1.h:225-240`). At RTF 1 the budget is 20 ms, so this copy alone takes 15-30 % of
  it. **[E]**
- Image bytes per robot per control step: RGB 2.76 MB + depth 1.84 MB (16UC1) = 4.6 MB. At RTF 0.23: 53 MB/s per robot,
  212 MB/s for 4 robots. At RTF 1 it would be 230 MB/s per robot. **[E]**
- `LP_NUM_THREADS`: its effect cannot be measured read-only. The two llvmpipe threads are not on the lockstep path.

## 3. Why the real-time factor drops

circus runs in lockstep: after each 2 ms physics substep it waits for every robot's command
(`RobotManager::receiveCommandMessagesSHM`). The chain is: circus → shared memory → simbridge main thread (200 us ROS
timer) → DDS → booster-motion → DDS → simbridge → shared memory → circus.

Thread times over 10 s (`/proc/.../schedstat`) **[M]**:

| Thread | Run | Run-queue wait | Switches/s |
|---|---|---|---|
| circus spqr::Simulation | 14.2 % | 16.1 % | 2811 |
| simbridge main, robot 1 / 2 / 3 / 4 | 7.3 / 7.7 / 7.6 / 7.5 % | 71.0 / 68.6 / 71.5 / 71.2 % | 1760-1960 |
| booster-motion control thread (SCHED_FIFO) | 3.7 % | 0.0 % | 188 |
| circus llvmpipe-0 | 32.2 % | 31.0 % | 332 |

- The simbridge main thread is the bottleneck. It is a normal (CFS) thread, and it wakes about 1800 times per second.
  Each time, about 5 runnable threads per CPU are ahead of it (load 80 / 16 vCPU). **[M]**
- The booster-motion control threads are fine: SCHED_FIFO, affinity 0-15 (the unpin loop in `vm_session.sh` works),
  0 % wait. Their DDS threads are CFS and wait 13-15 %. **[M]**
- The simbridge main thread also carries the images: `fillImageMsg_` 6.3 % and UDP `sendto` 16.6 % of its samples.
  The DDS send of 4.6 MB per frame runs in the same thread that relays the lockstep. **[M]**
- One 2 ms substep takes about 8.7 ms of wall time (RTF 0.23). In sim_fast 2v2 it takes 2.1-2.2 ms (RTF 0.91-0.96). **[E]**

CPU split of the whole server (perf, all CPUs, 10 s) **[M]**:

| Consumer | Share of 16 vCPU | Cores |
|---|---|---|
| Maximus × 4, ONNX Runtime spin (`WorkerLoop` + `RunInParallel`) | 74.5 % | 11.9 |
| Maximus × 4, YOLO kernels | 6.7 % | 1.1 |
| Maximus × 4, all other code | about 5 % | 0.8 |
| circus (all threads) | about 7 % | 1.1 |
| booster-motion × 4 | 2.3 % | 0.37 |
| simbridge × 4 | 2.0 % | 0.32 |

## 4. Fixes, ranked by expected gain (none applied)

| # | Fix | Where | Expected gain | Label |
|---|---|---|---|---|
| 1 | Cap the ONNX Runtime pool and turn off spin-wait. Add before the early return at line 34: `opts.SetIntraOpNumThreads(2); opts.SetInterOpNumThreads(1); opts.AddConfigEntry("session.intra_op.allow_spinning", "0");` (optional: read the count from an env var such as `SPQR_NN_THREADS`). It applies to every `NeuralNetwork`, the RL `Policy` classes too. Needs a Maximus rebuild. | `/home/xps/work/spqr-merge/src/app/utils/nn/NeuralNetwork.cpp:31-35` | The main gain is fewer runnable threads: about 80 → about 15, which cuts the 70 % run-queue wait of simbridge. The 11.9 cores of spin become real work: with no spin, each Perception thread runs inferences back to back at about 6-7 Hz (0.3 core-s ÷ 2 threads), about 2 cores per robot, about 8 cores for 4 robots. That leaves about 4-5 cores for circus, booster-motion and simbridge in a 2v2. RTF from 0.23 to about 0.6-0.9 (then limited by fix 3). | E |
| 2 | Lower the detection rate. Perception `update_rate: 30` → `5` (or a setting that runs `ObjectDetector` every Nth new frame). With fix 1 the rate has an effect only below about 6 Hz; the saving per robot is about 2 − rate × 0.3 cores (5 Hz: about 0.5 core per robot, 2 cores for 4). Necessary from 3v3 up: 5v5 × 2 threads = 20 cores > 16, so a 5v5 needs about 3 Hz, or 1 intra-op thread. `ImageDumper` is in the same node and slows with it. Without fix 1 this alone helps little: the 16-thread pools still spin during each inference. | `/home/xps/work/spqr-merge/src/app/config/scenarios/sim_real.yaml:120` | 2v2: about 2 cores. 3v3 and 5v5: required to fit in 16 vCPU. | E |
| 3 | Render the robot cameras at 640x360, not 1280x720. Same pixels (see section 2), 4 × fewer bytes: 4.6 → 1.15 MB per robot per control step. Check that Maximus takes the intrinsics from `camera_info` (the simbridge camera-info-fix; `ObjectDetector` waits for `intrinsicsInitialized` "from topic"). | `/opt/circus/resources/robots/Booster-T1/instance.xml:42,44` (`resolution="640 360"`) | Physics-thread copy from about 6 ms to about 1.5 ms per control step; simbridge DDS traffic and SAMPLE_LOST 4 × less; no upscale in the GUI thread. | E |
| 4 | Publish images on every 2nd control step (25 Hz simulated, near the real camera's 30 Hz): add a counter to `publishImages`. | `/opt/circus/src/SimulationThread.cpp:104` | Halves the image cost again. | E |
| 5 | No-rebuild option: start Maximus with lower priority. In `[program:maximus]`, prefix the command with `nice -n 10` (all threads inherit it). CFS weight then is 110 against 1024 for simbridge and circus. The spin still burns CPU, so this is a stopgap only. | `/home/xps/work/spqr-merge/scripts/supervisord.conf:23` | Unknown; it should cut the simbridge run-queue wait. | not measured |
| 6 | Skip the camera render when images are off: guard the loop with the `--no-images` flag. | `/opt/circus/src/SimulationViewport.cpp:52-62` | About 0.9-1 core of circus in sim_fast. Not on the lockstep path, so CPU only. | E |
| 7 | Depth is not used (`useDepth: false`), but the Bridge waits for an RGB/depth/head-pose triple. Make depth optional when `useDepth` is false, and let circus skip it. | `/home/xps/work/spqr-merge/src/app/config/settings.yaml:44`, `src/app/nodes/bridge/Bridge.cpp:22-23` | Removes 1.84 of the 4.6 MB per frame (40 %). | E |

Fix 1 is the minimum for sim_real on CPU; fix 2 is needed from 3v3 up. Fix 3 is the next largest, because it is on
the lockstep path.

## 5. GPU inference on the Jetson AGX Orin (steps, not run)

This applies to the mappazzone tree (`/home/xps/work/spqr-merge`). The `/DATA/RoboCup/spqrbooster2026` checkout
(`feature/oraculum-tcm`) has a different backend (`CpuBackend` and native TensorRT behind `ENABLE_TENSORRT`).

How the code picks the GPU **[S]**:
- `YoloEngine` builds `NeuralNetwork(model, use_gpu=true)` (`src/app/utils/vision/YOLOEngine.cpp:13`).
- When `TensorrtExecutionProvider` is available and `SPQR_NN_CPU` is unset, it loads
  `NeuralNetwork::trt_model_path("det/det.onnx")` = `det/det_trt.onnx` (`src/app/utils/nn/NeuralNetwork.h:25-28`).
  That file is an EPContext model: one node with the TensorRT engine embedded (fp16, built by
  `tools/trt_engine/build_trt_engine.cpp:20-25`).
- It sets `session.disable_cpu_ep_fallback=1`, so a TensorRT failure stops Maximus at start.
- But if ONNX Runtime does not list the TensorRT provider at all, it loads `det.onnx` on the CPU with only
  `LOG_WARN "GPU requested but no GPU execution provider available, using CPU"` (`NeuralNetwork.cpp:68`).
- Robot runtime today (`tools/deploy/maximus.env`): `onnxruntime-jetson` 1.20.2 (prefix.dev/spqr, `pixi.toml:54`),
  CUDA 12.6 from `/usr/local/cuda-12.6`, TensorRT from `/usr/lib/aarch64-linux-gnu` (JetPack 6.1/6.2, TensorRT 10.3).

Steps for Maximus in a Docker container on the Orin:
1. On the robot, check the L4T version: `cat /etc/nv_tegra_release` (JetPack 6 = R36.x).
2. Install the NVIDIA container runtime if it is absent: `sudo apt install nvidia-container`, then
   `sudo nvidia-ctk runtime configure --runtime=docker` and `sudo systemctl restart docker`.
   Check that `docker info` lists the runtime `nvidia`.
3. Pick a base image that matches the L4T release, for example `nvcr.io/nvidia/l4t-jetpack:r36.4.0` (CUDA 12.6,
   TensorRT 10.3). On JetPack 6 the runtime mounts the Tegra driver libraries only; CUDA and TensorRT must be in the
   image. The alternative is read-only bind mounts of the host's `/usr/local/cuda-12.6` and
   `/usr/lib/aarch64-linux-gnu/libnvinfer*`. (To verify on the robot.)
4. Start the container with the GPU:
   `docker run --runtime nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all --network host ...`
   or with CDI: `sudo nvidia-ctk cdi generate --mode=csv --output=/etc/cdi/nvidia.yaml`, then
   `docker run --device nvidia.com/gpu=all ...` (Docker 25-27 also need `"features": {"cdi": true}` in
   `/etc/docker/daemon.json`).
5. Inside the container use the same `LD_LIBRARY_PATH` order as `tools/deploy/maximus.env`, so that
   `libonnxruntime_providers_tensorrt.so` finds `libnvinfer.so.10` and `libcudart.so.12`.
6. Do NOT set `SPQR_NN_CPU`. Set `SPQR_MODEL_PATH` to a folder with both `det/det.onnx` and `det/det_trt.onnx`.
7. The engine is valid only for the TensorRT version and the GPU it was built with. If the TensorRT in the container
   differs from the host's, rebuild it inside the container:
   `build/aarch64/tools/trt_engine/build_trt_engine <models>/det/det.onnx`
   (from the laptop: `pixi run robot build-engine det/det.onnx`, `scripts/robot.sh:135-145`).
8. Check the start log for `TensorRT execution provider requested` (`NeuralNetwork.cpp:55`), and make sure the
   `using CPU` warning is absent. Check `tegrastats` for GR3D load, and check that the Perception "out of cycle"
   warnings stop.
9. Apply fix 1 there too. The CPU pool of ONNX Runtime still exists with the TensorRT provider, and on the robot
   booster-motion keeps its control thread pinned to CPU 3 with SCHED_FIFO.
