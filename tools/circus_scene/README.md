# circus scene export

These tools rebuild the MuJoCo scene that circus builds, as a standalone folder that a browser
renderer can load. They use circus's own code. Nothing in the circus tree is changed.

## What it does

1. `export_scene.sh` clones circus at a given commit (public repo, no credentials).
2. It installs circus's own pixi environment from `pixi.lock` (`pixi install --frozen`, MuJoCo 3.3.3).
3. It configures circus's own `CMakeLists.txt` with one extra flag:
   `-DCMAKE_PROJECT_circus_INCLUDE=exporter.cmake`. That hook adds the target
   `circus_scene_export` (`export_scene.cpp`), linked to `circus-lib`. The exporter so gets
   circus's flags and its `PROJECT_ROOT`.
4. `circus_scene_export <scene.yaml>` calls `SceneParser(yaml).buildMuJoCoXml()`. It then compiles
   the XML through `spqr::MujocoContext`, the same path as `AppWindow::loadScene`. It prints the XML.
5. `package_scene.py` makes the folder `circus_scene_<name>/`:
   - `scene.xml`: the circus XML with each `<include>` inlined. Every `file=` points to `assets/...`.
     The `meshdir` attribute is removed. Nothing else changes.
   - `assets/`: only the meshes and textures that the scene references (37 files, about 21 MB).
   - `scene_index.json`: robot and ball names, body and geom id ranges, and qpos addresses.
   - `reference.png`: a render by the classic MuJoCo renderer at 1280x720 with circus's viewport settings.
   - Exactness check: it compiles the raw XML the circus way (cwd = circus root, parse from string).
     It compiles `scene.xml` from the folder. It compares every array of the two `MjModel`s.
     Only `mesh_pathadr`, `tex_pathadr`, `npaths` and `nbuffer` may differ; any other difference stops the run.
   - The folder is built as `<name>.tmp-<pid>` and renamed when complete.

## Run it

Docker (any x86-64 Linux host; 2 CPUs and 2 GB RAM are enough):

```bash
cd tools
docker build -t circus-scene-export .
mkdir -p work
docker run --rm --memory=2g --cpus=2 --user "$(id -u):$(id -g)" \
  -e HOME=/work/home -e PIXI_CACHE_DIR=/work/pixi-cache -e WORK=/work -e JOBS=2 \
  -v "$PWD/work:/work" circus-scene-export <circus-commit-or-branch> /work/out
# result: work/out/circus_scene_1v1/, work/out/circus_scene_5v5/
```

- Other scenes: add YAML paths after the output dir (relative to the circus root, or absolute).
- Keep `work/` to reuse the pixi environment and the build. A rebuild after a circus change then
  compiles only the changed files. The first run took about 12 minutes on 2 CPUs. `work/` grows to about 2.7 GB.
- Without Docker: install `git`, `make` and `pixi`. Make a Python venv with `mujoco==3.3.3 PyOpenGL`.
  Then run `PYTHON=<venv>/bin/python MUJOCO_GL=egl ./export_scene.sh <ref> <out>`. Use `osmesa` or `egl`.

### The field depends on who starts circus

`SceneParser` reads the simulation config and the field config from `$FRAMEWORK_PATH`
(or `$PIXI_PROJECT_ROOT`) when that tree has them. Otherwise it uses circus's own `resources/config`.

| Started by | Simulation config | Field |
|---|---|---|
| circus alone (`pixi run circus`) | circus `resources/config/simulation_configs/default.yaml` | `fieldSPQR`: 9 x 4.7 m |
| spqrbooster2026 `pixi run sim` (`FRAMEWORK_PATH` = maximus root) | maximus `src/app/sim/simulation_configs/default.yaml` | `fieldLarge`: 14 x 9 m, 0.05 m lines |

The circus scenes put the 5v5 robots at x = ±7 m. On `fieldSPQR` they stand outside the field.
To get the scene that the team runs, pass a maximus checkout (or only its
`src/app/config/fields` and `src/app/sim` folders) and the maximus scene files:

```bash
docker run ... -e FRAMEWORK_PATH=/work/maximus circus-scene-export <ref> /work/out-maximus \
  /work/maximus/src/app/sim/1v1.yaml /work/maximus/src/app/sim/5v5.yaml
```

### Automatic runs (CI)

`.github/workflows/circus-scene.yml` in this repository runs the export on GitHub Actions:

- **When:** nightly, on a manual start (`workflow_dispatch`, optional `circus_ref` and `force`), and on a push
  that changes these tools or the workflow.
- **What:** the circus commit that `SPQRTeam/spqrbooster2026` `main` pins (`external/circus`), with the maximus
  `src/app/sim` and `src/app/config/fields` folders (sparse checkout), so the scene is the one `pixi run sim` shows.
- **Version:** `scene_tag.sh` gives `circus-scene-<circus commit>-<config id>`. The workflow skips the run when a
  release with that tag exists.
- **Output:** a release of this repository with `circus_scene_1v1.tar.gz`, `circus_scene_5v5.tar.gz` and
  `manifest.json` (commits and SHA-256 of each archive), plus a build artifact with the reference renders.
- **Secret:** `SPQR_READ_TOKEN`, a fine-grained token with read-only *Contents* access to
  `SPQRTeam/spqrbooster2026`. Release assets of a public repository are public.
- **Gateway side:** `python3 tools/fetch_circus_scene.py` downloads the release that matches the local
  `spqrbooster2026` checkout (or the newest), checks the SHA-256 and unpacks it to `src/static/models/`.

## Driving the scene from telemetry

All values below are for Booster-T1 robots and circus `f8ffde6`. `scene_index.json` has the
values for each folder, so read them from there and do not hard-code them.

- **Robot names.** A robot is `<team>_<type>_<i>`, for example `red_Booster-T1_0`. `<i>` counts the
  players of a team in YAML order. A `name:` key in the YAML replaces the default name.
  Every `name`, `joint`, `objname` and `site` inside the robot gets the prefix `<robot>_`.
- **Root body and free joint.** The root body is `<robot>_Trunk`, a direct child of the world.
  Its `<freejoint/>` has **no name**. Find it as `jnt_qposadr[body_jntadr[trunk_id]]`.
  The qpos layout is `x y z qw qx qy qz` in the world frame.
- **Ball.** Body `ball` (body id 1), geom `ball_geom`, unnamed free joint at qpos 0..6.
  The start position is (0, 0, 0.4).
- **qpos order.** The ball comes first, then the robots in YAML order (first team in the YAML first).
  A T1 uses 30 qpos: 7 for the free joint and 23 for the hinges. Robot k starts at qpos 7 + 30k.
  `hinge_qposadr` maps each joint name (for example `red_Booster-T1_0_Head_pitch`) to its address.
- **Bodies and geoms.** World is body 0, the ball is body 1, robots start at body 2 (25 bodies each).
  The geoms of a robot are one contiguous range (`geom_ids`, 48 geoms each). The robot's bodies have
  `body_rootid == root_body_id`.
- **Team colour.** Only the Trunk visual mesh geom has the team colour, as `rgba`:
  red = (130, 36, 51)/255 → `0.509804 0.141176 0.2 1`; blue = (0, 103, 120)/255 → `0 0.403922 0.470588 1`
  (values from `include/robots/Robot.h`). The other links use the materials `metal` and `black`.
- **Jersey numbers.** Each Trunk has 9 geoms `<robot>_num_1` … `<robot>_num_9`. Each uses the mesh
  `numbers/<k>.obj` (scale 0.3) at pos (0.05, 0, 0.7), euler (1.57, 1.57, 0). All of them are in
  **geom group 4**. The robot's own number keeps the material `white`; the others get
  `rgba="1 1 1 0"` (invisible). A number above 9 shows no geom. `mjv_defaultOption` hides group 4, so
  circus sets `geomgroup[4] = 1` for the main view. Robot cameras keep group 4 hidden.
  To show another number at runtime, set the alpha of the `num_<k>` geoms.
- **Other groups.** Visual meshes are group 2 (shown). Collision geoms are group 3 (hidden by default).
  Field geoms are group 0.
- **Robots that are not present.** circus has no such mechanism: every robot in the YAML is always
  in the scene. In the browser, load the largest scene (5v5) and hide each absent robot.
  Hide every geom in its `geom_ids` range (set the alpha to 0, or skip it in the draw list).
  Do not only move the robot under the floor: the floor is a plane, and the camera can see under it.

## Reference render settings

These values come from `src/MujocoContext.cpp` and `src/SimulationViewport.cpp`:
`mjv_defaultOption` with `geomgroup[4] = 1`; a scene of 10000 geoms; a free camera with distance 15,
azimuth 90, elevation -45 and lookat (0, -1, 0). The state is `qpos0` after `mj_forward`.
The script raises `vis.global.offwidth/offheight` to 1280x720 at render time only, because the scene
keeps the MuJoCo default of 640x480. The render uses OSMesa (software OpenGL), not circus's Qt window,
so anti-aliasing can differ slightly.
