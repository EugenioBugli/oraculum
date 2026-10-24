"""Pixel comparison of two same-size RGB renders, and the hash of a scene package.

Usage: python compare.py reference.png browser.png out_prefix
Writes out_prefix_side_by_side.png (reference | browser | diff x4) and prints the metrics as JSON.
       python compare.py --scene-sha256 SCENE_PACKAGE_DIR
Prints scene_sha256() of a scene package (package_scenes.sh output).
       python compare.py --selftest
Checks that a scene_yaml path change keeps the scene hash and a content change alters it.
"""
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

LINE_MIN = 170  # a pixel is "white" when all channels are above this


def compare(ref_path, test_path, prefix):
    a = np.asarray(Image.open(ref_path).convert("RGB")).astype(np.int16)
    b = np.asarray(Image.open(test_path).convert("RGB")).astype(np.int16)
    assert a.shape == b.shape, (a.shape, b.shape)
    line = a.min(axis=2) > LINE_MIN
    diff = np.abs(a - b)
    mse = float(np.mean(diff.astype(np.float64) ** 2))
    metrics = {
        "size": [a.shape[1], a.shape[0]],
        "mean_abs_diff_0_255": round(float(diff.mean()), 3),
        "pct_pixels_diff_gt_16": round(100.0 * float(np.mean(diff.max(axis=2) > 16)), 3),
        "psnr_db": round(10 * np.log10(255.0**2 / mse), 2) if mse > 0 else float("inf"),
        # white field lines (and other near-white pixels) of the reference that stay near-white: thin lines
        # that break up into dashes score low here, while PSNR hardly moves
        "line_keep_pct": round(100.0 * float(np.mean(b.min(axis=2)[line] > LINE_MIN)), 1) if line.any() else 100.0,
    }
    d4 = np.clip(diff * 4, 0, 255).astype(np.uint8)
    Image.fromarray(d4).save(prefix + "_diff.png")
    Image.fromarray(np.hstack([a.astype(np.uint8), b.astype(np.uint8), d4])).save(prefix + "_side_by_side.png")
    return metrics


def scene_sha256(package_dir):
    """SHA-256 of the files B2Viewer loads (files.json of the package), in a fixed order: the same scene
    gives the same hash wherever it was exported. Stored next to the MSAA references (refs_msaa/).
    scene_index.json is hashed without "scene_yaml" (the path of the yaml on the exporting machine, e.g.
    /work/maximus/... or /maximus/...), so moving the exporter's mount does not change the hash."""
    files = json.load(open(os.path.join(package_dir, "files.json")))["files"]
    h = hashlib.sha256()
    for f in sorted(files):
        data = open(os.path.join(package_dir, f), "rb").read()
        if f == "scene_index.json":
            index = json.loads(data)
            index.pop("scene_yaml", None)
            data = json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
        h.update(f"{f}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    return h.hexdigest()


def selftest():
    """The scene hash ignores scene_yaml but sees a change in scene.xml or in any other scene_index.json field."""
    import tempfile

    def pkg(xml, yaml, qposadr):
        d = tempfile.mkdtemp()
        index = {"scene_yaml": yaml, "robots": [{"name": "r1", "freejoint": {"qposadr": qposadr}}]}
        for name, text in [("files.json", json.dumps({"files": ["scene.xml", "scene_index.json"]})),
                           ("scene.xml", xml), ("scene_index.json", json.dumps(index, indent=1))]:
            open(os.path.join(d, name), "w").write(text)
        return scene_sha256(d)

    base = pkg("<mujoco/>", "/work/maximus/src/app/sim/5v5.yaml", 0)
    assert pkg("<mujoco/>", "/maximus/src/app/sim/5v5.yaml", 0) == base, "scene_yaml path changed the hash"
    assert pkg("<mujoco />", "/work/maximus/src/app/sim/5v5.yaml", 0) != base, "scene.xml change not seen"
    assert pkg("<mujoco/>", "/work/maximus/src/app/sim/5v5.yaml", 7) != base, "scene_index.json change not seen"
    print("selftest ok")


if __name__ == "__main__":
    if sys.argv[1] == "--selftest":
        selftest()
    elif sys.argv[1] == "--scene-sha256":
        print(scene_sha256(sys.argv[2]))
    else:
        print(json.dumps(compare(*sys.argv[1:4])))
