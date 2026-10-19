"""Native reference: MuJoCo classic renderer on OSMesa, window buffer, no MSAA (as Spike A).

Usage: python reference.py SCENE_DIR POSES.json OUT_DIR [--sizes 1280x720 780x780] [--cam X Y Z DIST AZ EL]
Writes OUT_DIR/<pose>_<W>x<H>_reference.png for every pose in POSES.json and every size, and
OUT_DIR/reference_info.json (MuJoCo and OpenGL versions). The calls are circus's
(MujocoContext.cpp + SimulationViewport.cpp); qpos is set, then mj_forward.
"""
import argparse
import json
import os

os.environ.setdefault("MUJOCO_GL", "osmesa")
import mujoco  # noqa: E402
import numpy as np  # noqa: E402
from OpenGL import GL  # noqa: E402
from PIL import Image  # noqa: E402


def render_all(scene_dir, poses, out_dir, sizes, cam):
    m = mujoco.MjModel.from_xml_path(os.path.join(scene_dir, "scene.xml"))
    d = mujoco.MjData(m)
    info = {"mujoco": mujoco.__version__, "extent": float(m.stat.extent),
            "znear": float(m.vis.map.znear * m.stat.extent), "zfar": float(m.vis.map.zfar * m.stat.extent)}
    for W, H in sizes:
        gl = mujoco.GLContext(W, H)
        gl.make_current()
        info["gl"] = {k: GL.glGetString(v).decode() for k, v in
                      (("version", GL.GL_VERSION), ("renderer", GL.GL_RENDERER))}
        opt = mujoco.MjvOption()
        mujoco.mjv_defaultOption(opt)
        opt.geomgroup[4] = 1
        c = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(c)
        c.lookat[:] = cam[:3]
        c.distance, c.azimuth, c.elevation = cam[3:]
        scene = mujoco.MjvScene(m, 10000)
        ctx = mujoco.MjrContext(m, mujoco.mjtFontScale.mjFONTSCALE_100)
        info["window_samples"] = ctx.windowSamples
        vp = mujoco.MjrRect(0, 0, W, H)
        for pose in poses:
            d.qpos[:] = pose["qpos"]
            mujoco.mj_forward(m, d)
            mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_WINDOW, ctx)
            mujoco.mjv_updateScene(m, d, opt, None, c, mujoco.mjtCatBit.mjCAT_ALL, scene)
            mujoco.mjr_render(vp, scene, ctx)
            rgb = np.zeros((H, W, 3), np.uint8)
            mujoco.mjr_readPixels(rgb, None, vp, ctx)
            out = os.path.join(out_dir, f"{pose['name']}_{W}x{H}_reference.png")
            Image.fromarray(np.flipud(rgb)).save(out)
            print(out, flush=True)
        ctx.free()
        gl.free()
    with open(os.path.join(out_dir, "reference_info.json"), "w") as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_dir")
    ap.add_argument("poses")
    ap.add_argument("out_dir")
    ap.add_argument("--sizes", nargs="+", default=["1280x720", "780x780"])
    ap.add_argument("--cam", type=float, nargs=6, default=[0, -1, 0, 15, 90, -45])
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    sizes = [tuple(int(v) for v in s.split("x")) for s in a.sizes]
    render_all(a.scene_dir, json.load(open(a.poses))["poses"], a.out_dir, sizes, a.cam)
