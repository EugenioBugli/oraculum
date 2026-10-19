# B2 renderer: circus scene in the browser, MuJoCo classic renderer replayed on WebGL2

MuJoCo 3.3.3 runs in WebAssembly: the engine, `mjv_updateScene` **and** the classic renderer
(`mjr_makeContext`, `mjr_render`), all unchanged. The renderer talks to a small OpenGL 1.5 shim
(`src_b2/glshim.c`) instead of a GPU. The shim records display lists as vertex/index arrays (once)
and every `glCallList` as one instance with its GL state. `src_b2/b2.js` replays the frame on
WebGL2 with shaders that implement the GL 1.5 fixed-function equations. The view options are
circus's (`MujocoContext.cpp`, `SimulationViewport.cpp`): `mjv_defaultOption` with `geomgroup[4] = 1`,
`mjv_makeScene(10000)`, `mjr_makeContext(mjFONTSCALE_100)`, `mjFB_WINDOW`, `mjCAT_ALL`. MSAA is on by
default, as circus's window (`CircusApplication.cpp`: `QSurfaceFormat::setSamples(4)`).

## Files

| File | Role |
|---|---|
| `src_b2/main.c`, `src_b2/glshim.{c,h}`, `src_b2/gen_stubs.py` | WASM engine: MuJoCo + GL shim + typed stubs for every GL entry point |
| `src_b2/b2.js` | `B2Viewer` (the API below) and the WebGL2 replay |
| `src_b2/index.html` | test page (query parameters in its header) |
| `build.sh` | renderer bundle (`b2_engine.js`, `b2_engine.wasm`, `b2.js`, `index.html`) |
| `package_scenes.sh` | scene packages for `load()` (scene folder + `files.json`) |
| `modal_b2.py` | build and tests on Modal |
| `poses.py`, `reference.py` | test poses; native references (MuJoCo 3.3.3, OSMesa, no MSAA) |
| `circus_ref.c`, `msaa_refs.py`, `refs_msaa/<scene>/` | native 4x MSAA references of two GPUs ("what circus shows"), committed with the scene hash |
| `shot.py`, `compare.py` | browser renders + pixel test (exit 0 pass, 3 pixel failure, 4 reference out of date, 2 other failure) |
| `pixeltest.sh` | one CI pixel-test job (`SCENE DEPTH msaa\|exact`); runs the same way on a laptop |
| `api_check.py` | functional checks of the API (19 checks, SwiftShader) |
| `gpu_fps.py`, `gpu_batch.sh` | fps on this laptop's GPUs (Chrome, ANGLE) |
| `../.github/workflows/oraculum-renderer.yml` | CI (below) |

Layout that the pages, tests and release use: `<root>/b2_bundle/` (renderer) next to
`<root>/b2_scenes/<scene>/` (scene packages `maximus_5v5`, `maximus_1v1`).

## API (`b2_bundle/b2.js`, `window.B2Viewer`)

```js
// create: WebGL2 context; with opts.scene, also load(). Errors have e.code:
// 'B2_NO_WEBGL2' (no WebGL2), 'B2_ENGINE' (b2_engine.js/.wasm), 'B2_SCENE' (scene package).
const v = await B2Viewer.create(canvas, {
  scene: 'b2_scenes/maximus_5v5',  // optional; URL relative to the page
  antialias: true,      // default true: 4 samples per pixel as circus's window: MSAA (gl.SAMPLES, 4 in Chrome) in
                        // ext mode, 4 jittered passes in d24/fragdepth (see "Depth modes"). Fixed per canvas.
  depth: 'auto',        // 'auto' = 'ext' with EXT_clip_control, else 'd24' (see "Depth modes")
  maxTexture: undefined,// default 2048 on touch devices (pointer: coarse), 0 = full size elsewhere
  engineUrl: undefined, // default: the folder of b2.js
  preserve: false,      // preserveDrawingBuffer (screenshots)
  log: console.log,
});
await v.load('b2_scenes/maximus_1v1');     // replace the scene at run time (a new engine instance)

v.listRobots();                            // [{name: 'red_Booster-T1_0', team: 'red', number: 1}, ...]
v.setRobotState(name, {x, y, yaw, z});     // m, rad about +z (0 = facing +x); z default: start height. -> bool
v.setJoints(name, {AAHead_yaw: 0.3});      // MJCF joint names without the robot prefix (AgentMsg.joints). -> count set
v.setBall(x, y, z);                        // z default: ball radius (0.112 m, on the ground). -> bool
v.setRobotVisible(name, false);            // geoms and sites left out of the scene (not moved under the floor)
v.setBallVisible(false);
v.setNumber(name, 7);                      // jersey number 1..9 as circus draws it; other n: no number
v.render();                                // mj_kinematics + mj_comPos + mj_camlight, mjv_updateScene, mjr_render, replay
                                           // returns frame stats, or null while loading or with the context lost
v.requestRender();                         // render once on the next animation frame

v.setCamera([0, -1, 0], 15, 90, -45);      // lookat, distance, azimuth, elevation (mjvCamera, free)
v.getCamera();                             // {lookat, distance, azimuth, elevation}
v.resetCamera();                           // circus viewport camera (above)
v.orbit(reldx, reldy);                     // mjv_moveCamera(mjMOUSE_ROTATE_V): azimuth -= 180*reldx, elevation -= 180*reldy
v.pan(reldx, reldy);                       // mjMOUSE_MOVE_H; in viewport heights: the scene follows the pointer
v.zoom(factor);                            // distance /= factor, within MuJoCo's limits
v.moveCamera(action, reldx, reldy);        // any mjtMouse action (B2Viewer.MOUSE)
const detach = v.attachControls(el, onChange);  // mouse as circus (left drag = move, shift+left or middle = rotate,
                                           // wheel = zoom); touch: 1 finger rotates, 2 fingers move + pinch-zoom

v.getViewProjection();                     // {view, proj, viewProj (Float32Array(16), column-major), width, height}
v.project(x, y, z);                        // world/field point -> [px, py] canvas pixels, top-left origin; null if behind
v.getQpos(); v.setQpos(q);                 // the whole state (scene_index.json has the addresses)
v.glUnimplemented; v.glUnsupported;        // GL calls/features the shim lacks since start (load + frames): must be 0
v.unimplementedAtLoad; v.glIssues;         // the same at load time; the log lines
v.samples; v.depthMode; v.ready; v.lost;
v.setViewOption('flag' | 'geomgroup', i, value);  // debug only (negative test): breaks circus equality
```

`viewProj` is MuJoCo's own camera (the matrices `mjr_render` loaded); its z is MuJoCo's reverse-Z.
`setRobotState` writes only the free joint: a fallen robot needs `setQpos`.

**WebGL context loss.** The viewer prevents the default, `render()` returns `null`, and on
`webglcontextrestored` it loads the scene again in a new engine and puts back pose, camera, hidden
robots and numbers, renders, and fires a `b2restored` event on the canvas. The image after a restore is
bit-identical (measured, SwiftShader). It takes one scene load (about 4 s on a laptop, 13 s in the Android
emulator). The old engine is freed: 1 live `WebAssembly.Memory` after each of 3 restores (measured, Chrome).

## Results (measured)

Pixel test against the native 4x MSAA references (`pixeltest.sh SCENE DEPTH msaa`, the CI configuration,
run 2026-10-12 in the Playwright 1.58 image on this laptop; SwiftShader: 4 samples, plain mean). Worst of
qpos0 + pose1..3 at 1280x720 and 780x780; per image the better of the Arc and the RTX reference counts.

| Scene, depth | PSNR | % px > 16 | white line pixels kept |
|---|---|---|---|
| maximus_5v5, ext | 32.12 dB | 2.42 % | 95.0 % |
| maximus_5v5, d24 (4 jittered passes) | 37.61 dB | 1.22 % | 98.6 % |
| maximus_1v1, ext | 32.16 dB | 2.33 % | 95.1 % |
| maximus_1v1, d24 (4 jittered passes) | 37.70 dB | 1.20 % | 98.6 % |
| for scale: d24, 2x2 supersampling (round 1 of 2026-10-12) | 33.46 dB | 2.21 % | 93.3 % (2-px stipple on the lines: fails the d24 bar) |
| for scale: d24 with MSAA (before 2026-10-12) | 31.74 dB | 2.42 % | 63.1 % (dashed lines: fails) |

Same measure in browsers: Chrome on the Arc ext 33.8 dB / 94.7 %. d24 with 4 jittered passes, qpos0 1280x720
against the Arc reference: 41.6 dB / 99.3 % in Chrome on the Arc and on the RTX, Firefox 146 and the Android emulator
(Chrome 124), the same image in all four (2x2 supersampling: 33.6 dB / 93.8 %).

Pixel test, CI configuration: Playwright 1.58 Chromium, SwiftShader, no MSAA, against native
MuJoCo 3.3.3 (OSMesa, window buffer, no MSAA), circus camera. Worst of qpos0 + pose1..3 (seed 20261011).
Run on Modal 2026-10-12 (`modal run modal_b2.py --step test`).

| Scene, depth | 1280x720 PSNR / % px > 16 | 780x780 PSNR / % px > 16 |
|---|---|---|
| maximus_5v5, ext | 33.70 dB / 0.256 % | 30.29 dB / 0.632 % |
| maximus_5v5, d24 | 36.77 dB / 0.110 % | 38.51 dB / 0.078 % |
| maximus_1v1, ext | 33.68 dB / 0.255 % | 30.25 dB / 0.634 % |
| maximus_1v1, d24 | 36.76 dB / 0.106 % | 38.68 dB / 0.073 % |
| negative: textures off (`visflag=1:0`) | 4.62 dB / 97.6 % (fails, as it must) | 5.76 dB / 98.0 % |
| not caught: jersey numbers off (`geomgroup=4:0`) | 36.07 dB / 0.156 % | 36.96 dB / 0.159 % |

`ext` on SwiftShader is 0.25 dB above the 30 dB limit at 780x780: SwiftShader's hardware depth
z-fights the field lines differently from OSMesa's 24-bit buffer. On a real GPU `ext` is near exact
(below). The jersey numbers cover about 0.05 % of the image: the global thresholds do not see them.

Laptop GPUs (Chrome headless, ANGLE gl-egl), against native MuJoCo 3.3.3 on the same GPU with circus's
calls and window format (4x MSAA window as circus, or no MSAA; references made 2026-10-12 by a separate tool):

| Intel Arc (Meteor Lake) | worst PSNR / % px > 16 |
|---|---|
| B2 ext, no MSAA vs native, no MSAA | 60.2 dB / 0.001 % (d24 and fragdepth: 67.4 dB at 1280x720) |
| B2 ext, no MSAA vs OSMesa | 44.7 dB / 0.003 % |
| B2 ext, MSAA vs native 4x MSAA window ("what circus shows") | 33.8 dB / 1.30 % (best 40.0 dB / 0.57 %) |
| B2 ext, MSAA vs native 4x MSAA framebuffer object (qpos0) | 38.6 dB / 1.13 % |
| B2 ext, no MSAA vs native 4x MSAA window | 28.1 dB / 2.76 % |
| for scale: native Arc MSAA window vs native RTX MSAA window | 35.8 dB / 1.66 % |
| for scale: native Arc MSAA window vs native Arc MSAA framebuffer object | 32.8 dB / 2.13 % |

With MSAA the image depends on the GPU and even on the surface type: the differences sit on sub-pixel
geometry (the goal nets). B2 with MSAA is as close to circus on the Arc as circus on the RTX is.
SwiftShader with MSAA vs the native Arc MSAA window: 31.7-34.8 dB, 2.4 % px > 16 (the CI's msaa check, above).

fps on the Intel Arc (load average 1.3-2; 60 fps = the display cap in every case):

| 1280x720 | no MSAA | MSAA (4 samples) |
|---|---|---|
| ext: ms per frame, synced | 4.7-4.9 | 6.1-6.2 |
| ext: ms per frame, 120 queued | 1.8-2.7 | 2.2-2.4 |
| d24: ms per frame, synced | 5.0 | 6.7 |

MSAA costs about 1.3 ms per synced frame (+27 %) at 1280x720. At load average 10-13 the ext numbers
were 4.7 / 6.0 ms. Earlier spike numbers: RTX 4050 ext 3.5 ms synced; Intel d24 without other load 9-17 ms.

Sizes: `b2_engine.wasm` 2.49 MB (0.80 MB gzip), `b2_engine.js` 21 kB gzip, `b2.js` 41 kB (14 kB gzip). Scene package: 21 MB
(5v5 and 1v1, mostly PNG). WASM heap after load: 246 MB (5v5), 227 MB (1v1). GPU: geometry 13 MB;
textures about 145 MB as uploaded, 78 MB with `maxTexture` 2048 (the touch default). Load in SwiftShader:
download 0.5 s, load 3.7-4.6 s (`mj_loadXML` 1.6 s). GL calls the shim lacks: 0 at load, 0 per frame.

## Depth modes (`depth`, `?depth=`)

MuJoCo renders reverse-Z with `glClipControl(GL_LOWER_LEFT, GL_ZERO_TO_ONE)`; the circus field layers are 1-3 mm apart.

- `ext`: `EXT_clip_control`, hardware depth. Default when the extension exists.
- `d24`: the fragment shader writes MuJoCo's [0, 1] depth, rounded to 24 bits as in circus's window. No extension needed.
  Default when `EXT_clip_control` is missing (Firefox, Chrome on many Android devices). Costs early-Z (fill rate).
- `fragdepth`: as d24 without the rounding (float precision).

With a shader-written depth, MSAA gives a pixel one depth value for all its samples, so the 5 cm field lines broke
up into dashes (62 % of the line pixels kept). In d24 and fragdepth, `antialias` therefore draws the frame 4 times
without MSAA (4 RGBA8 targets of the canvas size, one depth 24 / stencil 8 buffer), each time shifted to one sample
position of standard 4x MSAA (`SS_SAMPLES` in b2.js), and writes the mean of the 4 images to the canvas: 4 samples per
pixel, plain mean, as circus's MSAA on Mesa. `render()` stats have `supersample: true`. Until 2026-10-12 this was one
2x2 supersampled frame; an ordered 2x2 grid has only 2 sample columns per pixel, so the field lines had a regular
2-px stipple (measured, see Results; depth was ruled out: without antialias d24, fragdepth and ext give the same
image). Cost: 4x the WebGL draw calls of a frame. Android emulator (824x824 canvas): 7.8 ms per synced frame against
4.9 ms for the 2x2 frame, 60 fps (measured).
- `off`: MuJoCo's own no-clip-control projection; the field z-fights.

## Build and test

- `./build.sh 3.3.3 b2_bundle` (inside `emscripten/emsdk:3.1.74`); `./package_scenes.sh b2_scenes DIR[:NAME]...`.
- Modal (`B2_SCENES` = folder with `circus_scene_maximus_5v5/` and `circus_scene_maximus_1v1/`):
  `modal run modal_b2.py --step refs|build|test [--out DIR] [--scenes-out DIR] [--tag T] [--aa 1]`.
  App `oraculum-b2-renderer`, Volume `oraculum-spike2-b2-cache`.
- Browser tests: `renderer/pixeltest.sh SCENE DEPTH msaa|exact` from the repository root (layout: `site/b2_bundle`,
  `site/b2_scenes/<scene>`, `refs/` for exact), `python3 api_check.py ROOT`.
- MSAA references, when the CI says "reference out of date" (needs this laptop's GPUs or two GPUs with an NVIDIA and a
  Mesa driver): build `circus_ref` (line in `circus_ref.c`), then
  `python3 msaa_refs.py ./circus_ref ../b2_scenes/maximus_5v5 poses.json refs_msaa/maximus_5v5` (1v1: `poses_1v1.json`)
  and commit `refs_msaa/`. Laptop GPU fps: `python3 gpu_fps.py http://HOST/b2_bundle OUT.json --query "&aa=1"`.

## CI (`.github/workflows/oraculum-renderer.yml`, not pushed)

1. `scene`: the newest `circus-scene-*` release (or the `scene_tag` input; without a release, the newest
   `circus-scene.yml` artifact), SHA-256 checked against its `manifest.json`. Its `circus_scene_5v5`/`_1v1`
   are the maximus scenes (exported with `FRAMEWORK_PATH` = maximus) and become `maximus_5v5`/`maximus_1v1`.
2. `build`: `build.sh 3.3.3` in `emscripten/emsdk:3.1.74` (MuJoCo build cached).
3. `refs`: `poses.py` + `reference.py` for both scenes (OSMesa, no MSAA), for the exact check.
4. `pixeltest` (`pixeltest.sh`): ext and d24 x 5v5 and 1v1 x two checks, SwiftShader.
   - `msaa`: the pages' look (antialias on) against `refs_msaa/` (GitHub runners have no GPU and llvmpipe has no MSAA,
     so these are committed). ext fails below 31.5 dB, at 3 % px > 16 or more, below 90 % of the white line pixels
     kept; d24 below 36 dB, at 2 % or more, below 97 % (catches the dashed and the stippled d24 lines); both with
     exit 4 when the scene hash differs from `refs_msaa/<scene>/scene.sha256`.
   - `exact`: no MSAA against OSMesa. Fails below 36 dB or at 0.2 % px > 16 (d24), below 29.5 dB or at 1 % (ext:
     SwiftShader's own depth buffer z-fights differently from OSMesa's 24 bits).
   Both fail on any unimplemented or unsupported GL call (load or frames) or a depth mode other than the one asked
   for. Plus the negative test (textures off, exact d24): it must end with the pixel-test failure (exit 3).
5. `api`: `api_check.py`.
6. `publish` (default branch, scene from a release, all tests passed): `b2_bundle.tar.gz`,
   `b2_scene_maximus_5v5.tar.gz`, `b2_scene_maximus_1v1.tar.gz`, `b2_manifest.json` uploaded to the same
   `circus-scene-<circus>-<config>` release (`--clobber`).

A new circus scene release starts the workflow (`workflow_run`). A MuJoCo version change in circus needs
`MUJOCO_VERSION` here and a new scene export.

Known limits: the view options are written three times (here in `main.c`, `reference.py`,
`tools/circus_scene/package_scene.py`), so a change of circus's view options is not detected; the global
thresholds miss changes of about 0.05 % of the image (jersey numbers).

## Not supported (logged once, counted in `glUnsupported`)

Shadows (lights with castshadow), reflections (reflectance > 0 on planes/boxes), text labels, wireframe,
skins/flexes, immediate-mode line geoms. The circus viewport uses none of them.
