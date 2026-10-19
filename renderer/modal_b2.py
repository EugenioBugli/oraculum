"""B2 renderer builds and tests on Modal (CPU containers). Each step: `modal run modal_b2.py --step <name>`.

  poses   poses.json for the 5v5 scene (fixed seed), from the scene's own joint ranges
  refs    native references, 5v5 and 1v1: MuJoCo 3.3.3 classic renderer, OSMesa, window buffer, no MSAA
  build   renderer bundle (emscripten/emsdk:3.1.74, build.sh) -> --out (default ./b2_bundle) and scene
          packages (package_scenes.sh) -> --scenes-out (default ./b2_scenes)
  test    pixel tests in headless Chromium (SwiftShader, the Playwright 1.58 image the CI uses):
          ext and d24 x 5v5 and 1v1, the negative test (one circus view option changed) and
          api_check.py -> ./results/<tag>
The scene folders come from $B2_SCENES (holds circus_scene_maximus_5v5 and circus_scene_maximus_1v1).
Build cache, bundle and references stay in the Volume oraculum-spike2-b2-cache.
"""
import io
import os
import pathlib
import subprocess
import tarfile

import modal

HERE = pathlib.Path(__file__).resolve().parent
SCENES = pathlib.Path(os.environ.get("B2_SCENES", HERE / "scenes"))
SCENE_NAMES = ["circus_scene_maximus_5v5", "circus_scene_maximus_1v1"]
MJ = "3.3.3"
PW = "1.58.0"

app = modal.App("oraculum-b2-renderer")
vol = modal.Volume.from_name("oraculum-spike2-b2-cache", create_if_missing=True)
SCRIPTS = ["poses.py", "reference.py", "shot.py", "compare.py", "api_check.py", "build.sh", "package_scenes.sh"]
# the test cases of the CI workflow (.github/workflows/oraculum-renderer.yml): depth, scene, aa
CASES = [(d, s) for s in ("maximus_5v5", "maximus_1v1") for d in ("ext", "d24")]
LIMITS = "--min-psnr 30 --max-pct16 1"


def with_files(img, scenes=True):
    for s in SCRIPTS:
        img = img.add_local_file(HERE / s, f"/b2/{s}")
    for f in ("poses.json", "poses_1v1.json"):
        if (HERE / f).exists():
            img = img.add_local_file(HERE / f, f"/b2/{f}")
    img = img.add_local_dir(HERE / "src_b2", "/b2/src_b2")
    if scenes:
        for n in SCENE_NAMES:
            img = img.add_local_dir(SCENES / n, f"/scenes/{n}")
    return img


ref_img = with_files(
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libosmesa6", "libgl1")
    .pip_install(f"mujoco=={MJ}", "PyOpenGL", "numpy", "pillow")
    .env({"MUJOCO_GL": "osmesa", "PYOPENGL_PLATFORM": "osmesa"}))
emsdk_img = with_files(modal.Image.from_registry("emscripten/emsdk:3.1.74", add_python="3.11"))
pw_img = with_files(
    modal.Image.from_registry(f"mcr.microsoft.com/playwright/python:v{PW}-noble", add_python="3.12")
    .pip_install(f"playwright=={PW}", "numpy", "pillow")
    .env({"PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright"}), scenes=False)


def sh(cmd, cwd="/b2", check=True):
    print("+", cmd, flush=True)
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, check=check).returncode


def tar_dir(path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(path, arcname=".")
    return buf.getvalue()


@app.function(image=ref_img, cpu=2, timeout=600)
def poses():
    sh("python poses.py /scenes/circus_scene_maximus_5v5 /tmp/poses.json")
    return open("/tmp/poses.json").read()


@app.function(image=ref_img, cpu=4, memory=4096, timeout=1800, volumes={"/cache": vol})
def refs():
    out = f"/cache/refs-{MJ}"
    sh(f"[ -f {out}/pose3_780x780_reference.png ] || python reference.py /scenes/circus_scene_maximus_5v5 /b2/poses.json {out}")
    sh("python poses.py /scenes/circus_scene_maximus_1v1 /tmp/poses_1v1.json --count 3 --suffix _1v1")
    sh(f"python reference.py /scenes/circus_scene_maximus_1v1 /tmp/poses_1v1.json {out}")
    vol.commit()
    return open("/tmp/poses_1v1.json").read(), tar_dir(out)


@app.function(image=emsdk_img, cpu=8, memory=8192, timeout=3600, volumes={"/cache": vol})
def build(mj_version: str = MJ):
    out, scenes = f"/cache/b2_bundle-{mj_version}", "/cache/b2_scenes"
    sh(f"rm -rf {out} {scenes}")
    sh(f"BUILD=/cache/build MJ_SRC=/cache/src/mujoco-{mj_version} JOBS=8 bash /b2/build.sh {mj_version} {out}")
    sh(f"bash /b2/package_scenes.sh {scenes} " + " ".join(f"/scenes/{n}" for n in SCENE_NAMES))
    vol.commit()
    return tar_dir(out), tar_dir(scenes)


def site():
    """/site/b2_bundle + /site/b2_scenes from the Volume (the layout the CI and the README use)."""
    vol.reload()
    sh(f"mkdir -p /site && cp -r /cache/b2_bundle-{MJ} /site/b2_bundle && cp -r /cache/b2_scenes /site/b2_scenes")


@app.function(image=pw_img, cpu=4, memory=8192, timeout=3600, volumes={"/cache": vol})
def shots(depth: str, scene: str, aa: str = "0", query: str = "", sizes: str = "1280x720 780x780",
          ref_dir: str = "", ref_pattern: str = "{pose}_{size}_reference.png", timing: bool = False):
    site()
    out = "/tmp/out"
    poses = "/b2/poses_1v1.json" if "1v1" in scene else "/b2/poses.json"
    rc = sh(f"python shot.py /site {poses} {ref_dir or f'/cache/refs-{MJ}'} {out} --depth {depth} --aa {aa} "
            f"--scene ../b2_scenes/{scene} --sizes {sizes} --query '{query}' --ref-pattern '{ref_pattern}' "
            f"{'--timing' if timing else ''} {LIMITS}", check=False)
    return rc, tar_dir(out)


@app.function(image=pw_img, cpu=4, memory=8192, timeout=3600, volumes={"/cache": vol})
def api():
    site()
    rc = sh("python api_check.py /site --out /tmp/api.json", check=False)
    return rc, open("/tmp/api.json").read()


@app.local_entrypoint()
def main(step: str, out: str = "", scenes_out: str = "", tag: str = "", query: str = "", aa: str = "0"):
    def untar(data, dest):
        dest = pathlib.Path(dest)
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            t.extractall(dest)  # our own containers' output
        print("wrote", dest)

    if step == "poses":
        (HERE / "poses.json").write_text(poses.remote())
        print("wrote", HERE / "poses.json")
    elif step == "refs":
        poses_1v1, data = refs.remote()
        (HERE / "poses_1v1.json").write_text(poses_1v1)
        untar(data, out or HERE / "refs")
    elif step == "build":
        bundle, scenes = build.remote(MJ)
        untar(bundle, out or HERE / "b2_bundle")
        untar(scenes, scenes_out or HERE / "b2_scenes")
    elif step == "test":
        res = pathlib.Path(out or HERE / "results") / (tag or "test")
        cases = [(d, s, aa, query) for d, s in CASES]
        cases.append(("d24", "maximus_5v5", aa, query + "&visflag=1:0"))  # negative: textures off
        cases.append(("d24", "maximus_5v5", aa, query + "&geomgroup=4:0"))  # negative: jersey numbers off
        handle = api.spawn()
        for (d, s, a, q), (rc, data) in zip(cases, shots.starmap(cases)):
            name = f"{s}_{d}_aa{a}" + ("_neg_" + q.split("&")[-1].replace("=", "").replace(":", "_") if "&" in q else "")
            untar(data, res / name)
            print(f"{name}: exit {rc}" + (" (negative test: must be 3)" if "neg" in name else ""))
        rc, api_json = handle.get()
        (res / "api_check.json").write_text(api_json)
        print(f"api_check: exit {rc}")
    else:
        raise SystemExit(f"unknown step {step}")
