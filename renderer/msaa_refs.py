"""Native 4x MSAA references of "what circus shows on screen" for the CI pixel test (refs_msaa/<scene>/).

GitHub runners have no GPU and llvmpipe does not antialias, so these PNGs are made on a machine with GPUs
and committed. circus_ref.c makes circus's MuJoCo calls on an EGL pbuffer with circus's framebuffer (RGB8,
depth 24, stencil 8, 4 samples). The drivers resolve the samples differently (measured 2026-10-12 on the
Intel Arc and the RTX 4050): NVIDIA averages in sRGB space ("rtx", what circus shows on a display that runs on
the NVIDIA driver), Mesa plainly ("arc"). The CI compares each render with the nearer of the two.

Usage: python msaa_refs.py CIRCUS_REF SCENE_PACKAGE POSES.json OUT_DIR [--gpu rtx=RTX arc=Arc]
  CIRCUS_REF: the built circus_ref (build line in circus_ref.c); SCENE_PACKAGE: package_scenes.sh output.
  --gpu TAG=SUBSTRING: the EGL device whose GL_RENDERER contains SUBSTRING renders OUT_DIR/*_<TAG>.png.
Writes OUT_DIR/<pose>_<W>x<H>_<tag>.png for 1280x720 and 780x780 and OUT_DIR/scene.sha256. Run it again
(and commit the result) when the CI says "reference out of date".
"""
import argparse
import glob
import json
import os
import subprocess
import tempfile

from PIL import Image

from compare import scene_sha256

SIZES = ["1280x720", "780x780"]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("circus_ref")
    ap.add_argument("scene")
    ap.add_argument("poses")
    ap.add_argument("out_dir")
    ap.add_argument("--gpu", nargs="+", default=["rtx=RTX", "arc=Arc"])
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # cwd: MuJoCo writes MUJOCO_LOG.TXT there
        poses_txt = os.path.join(tmp, "poses.txt")
        with open(poses_txt, "w") as f:
            for p in json.load(open(a.poses))["poses"]:
                f.write(p["name"] + " " + " ".join(repr(float(x)) for x in p["qpos"]) + "\n")
        for g in a.gpu:
            tag, want = g.split("=", 1)
            subprocess.run([os.path.abspath(a.circus_ref), os.path.abspath(os.path.join(a.scene, "scene.xml")),
                            poses_txt, tmp, tag, want, "4", *SIZES], cwd=tmp, check=True)
        for ppm in glob.glob(os.path.join(tmp, "*.ppm")):
            Image.open(ppm).save(os.path.join(a.out_dir, os.path.basename(ppm)[:-4] + ".png"))
    with open(os.path.join(a.out_dir, "scene.sha256"), "w") as f:
        f.write(scene_sha256(a.scene) + "\n")
    print(a.out_dir, sorted(os.listdir(a.out_dir)))
