#!/usr/bin/env python3
"""Turn the raw MJCF from circus_scene_export into a standalone folder.

usage: package_scene.py <raw.xml> <circus_root> <out_dir> [--commit SHA] [--scene-yaml PATH]

out_dir gets: scene.xml (includes inlined, every file path relative), assets/ (only the
referenced meshes and textures), scene_index.json (names and qpos addresses for a
telemetry driver) and reference.png (classic renderer, circus viewport settings).
The folder appears only when complete (built under a temporary name, then renamed).

Exactness check: the raw XML is compiled the way circus does it (cwd = circus root,
parse from string) and compared array by array with the compiled scene.xml. Only
path-related arrays may differ.
"""

import argparse
import json
import os
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
import zlib

import mujoco
import numpy as np

MESH_TAGS = {"mesh", "hfield", "skin"}
TEAM_COLORS = {(130, 36, 51): "red", (0, 103, 120): "blue"}  # circus include/robots/Robot.h


def inline_includes(root, model_dir):
    # MuJoCo semantics: <include file=X/> is replaced by the children of X's <mujoco> root.
    while True:
        hits = [(p, i, c) for p in root.iter() for i, c in enumerate(list(p)) if c.tag == "include"]
        if not hits:
            return
        parent, idx, inc = hits[0]
        path = os.path.join(model_dir, inc.get("file"))
        sub = ET.parse(path).getroot()
        if sub.tag != "mujoco":
            sys.exit(f"included file {path} has root <{sub.tag}>, expected <mujoco>")
        parent.remove(inc)
        for k, child in enumerate(list(sub)):
            parent.insert(idx + k, child)


def relocate_files(root, model_dir, out_dir):
    # Raw XML is parsed from a string with cwd = circus root, so relative dirs resolve there.
    meshdir = texturedir = model_dir
    for comp in root.iter("compiler"):
        for attr in ("assetdir", "meshdir", "texturedir"):
            if comp.get(attr) is not None:
                d = os.path.join(model_dir, comp.attrib.pop(attr))
                if attr in ("assetdir", "meshdir"):
                    meshdir = d
                if attr in ("assetdir", "texturedir"):
                    texturedir = d
    resources = os.path.join(model_dir, "resources")
    copied = []
    for el in root.iter():
        extra = [a for a in el.attrib if a.startswith("file") and a != "file"]
        if extra:
            sys.exit(f"<{el.tag}> uses {extra}; package_scene.py only handles 'file'")
        if "file" not in el.attrib:
            continue
        base = meshdir if el.tag in MESH_TAGS else texturedir if el.tag == "texture" else None
        if base is None:
            sys.exit(f"unexpected file attribute on <{el.tag}>")
        src = os.path.normpath(os.path.join(base, el.get("file")))  # join keeps absolute paths
        rel = os.path.relpath(src, resources)
        if rel.startswith(".."):
            sys.exit(f"{src} is outside {resources}")
        dst = os.path.join(out_dir, "assets", rel)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
        el.set("file", "assets/" + rel.replace(os.sep, "/"))
    return copied


def compare_models(a, b):
    diffs = []
    for name in dir(a):
        if name.startswith("_"):
            continue
        try:
            va, vb = getattr(a, name), getattr(b, name)
        except Exception:
            continue
        if isinstance(va, np.ndarray):
            same = va.shape == vb.shape and np.array_equal(va, vb, equal_nan=va.dtype.kind == "f")
        elif isinstance(va, (int, float)) and not isinstance(va, bool):
            same = va == vb
        else:
            continue
        if not same:
            diffs.append(name)
    bad = [d for d in diffs if "path" not in d and d != "nbuffer"]
    return diffs, bad


def build_index(root, model, commit, scene_yaml):
    def name(obj, i):
        return mujoco.mj_id2name(model, obj, i)

    def free_joint(body_id):
        j = model.body_jntadr[body_id]
        if j < 0 or model.jnt_type[j] != mujoco.mjtJoint.mjJNT_FREE:
            return None
        return {"name": name(mujoco.mjtObj.mjOBJ_JOINT, j), "joint_id": int(j),
                "qposadr": int(model.jnt_qposadr[j]), "dofadr": int(model.jnt_dofadr[j])}

    # circus emits two <worldbody> sections (field + ball, then light + obstacles + robots).
    trunks = {b.get("name"): b for wb in root.findall("worldbody") for b in wb.findall("body") if b.get("name", "").endswith("_Trunk")}
    robots = []
    for bid in range(1, model.nbody):
        bname = name(mujoco.mjtObj.mjOBJ_BODY, bid)
        if model.body_parentid[bid] != 0 or bname not in trunks:
            continue
        robot = bname[: -len("_Trunk")]
        el = trunks[bname]
        geoms = el.findall("geom")
        shown = [g.get("name") for g in geoms if g.get("name", "").startswith(robot + "_num_") and g.get("rgba") != "1 1 1 0"]
        # SceneParser colours every class="visual" (or "<prefix>_visual", Booster-T2) geom of the Trunk. A Booster-K1
        # Trunk has no visual mesh geom (its meshes are group 1 without a class): only its shown number has the colour.
        visual = [g for g in geoms if g.get("class", "") == "visual" or g.get("class", "").endswith("_visual")]
        colored = [g for g in visual if g.get("rgba") and g.get("rgba") != "1 1 1 0"]
        color = next((g.get("rgba") for g in colored if "_num_" not in g.get("name", "")), None) or colored[0].get("rgba")
        rgb = tuple(round(float(v) * 255) for v in color.split()[:3])
        subtree = [i for i in range(model.nbody) if model.body_rootid[i] == bid]
        joints = {name(mujoco.mjtObj.mjOBJ_JOINT, j): int(model.jnt_qposadr[j])
                  for j in range(model.njnt) if model.body_rootid[model.jnt_bodyid[j]] == bid and model.jnt_type[j] != mujoco.mjtJoint.mjJNT_FREE}
        robots.append({
            "name": robot, "team": TEAM_COLORS.get(rgb), "trunk_rgba": color,
            "number": int(shown[0].rsplit("_", 1)[1]) if shown else None, "number_geom": shown[0] if shown else None,
            "root_body": bname, "root_body_id": bid, "body_ids": [min(subtree), max(subtree)],
            "geom_ids": [int(g) for g in np.flatnonzero(np.isin(model.geom_bodyid, subtree))[[0, -1]]],
            "freejoint": free_joint(bid), "hinge_qposadr": joints,
        })
    ball_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "ball")
    return {
        "circus_commit": commit, "scene_yaml": scene_yaml, "mujoco_version": mujoco.__version__,
        "nq": int(model.nq), "nv": int(model.nv), "nbody": int(model.nbody), "ngeom": int(model.ngeom),
        "qpos_free_layout": "x y z qw qx qy qz (world frame)",
        "ball": {"body": "ball", "body_id": int(ball_id), "geom": "ball_geom", "freejoint": free_joint(ball_id)},
        "robots": robots,
    }


def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render_reference(model, path, width=1280, height=720):
    # circus: MujocoContext (mjv_defaultOption, geomgroup[4]=1, mjv_makeScene 10000 geoms)
    # + SimulationViewport (free camera distance 15, azimuth 90, elevation -45, lookat 0 -1 0).
    # ponytail: offscreen buffer size is raised at render time only; the scene keeps its value.
    model.vis.global_.offwidth = max(model.vis.global_.offwidth, width)
    model.vis.global_.offheight = max(model.vis.global_.offheight, height)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    opt = mujoco.MjvOption()
    mujoco.mjv_defaultOption(opt)
    opt.geomgroup[4] = 1
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.azimuth, cam.elevation = 15.0, 90.0, -45.0
    cam.lookat[:] = [0.0, -1.0, 0.0]
    with mujoco.Renderer(model, height=height, width=width, max_geom=10000) as r:
        r.update_scene(data, camera=cam, scene_option=opt)
        write_png(path, r.render())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw_xml")
    ap.add_argument("circus_root")
    ap.add_argument("out_dir")
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--scene-yaml", default="")
    args = ap.parse_args()

    circus_root = os.path.abspath(args.circus_root)
    out_dir = os.path.abspath(args.out_dir)
    tmp = f"{out_dir}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)

    raw = open(args.raw_xml).read()
    root = ET.fromstring(raw)
    inline_includes(root, circus_root)
    copied = relocate_files(root, circus_root, tmp)
    ET.indent(root, "  ")
    ET.ElementTree(root).write(os.path.join(tmp, "scene.xml"), encoding="utf-8", xml_declaration=True)

    cwd = os.getcwd()
    os.chdir(circus_root)  # what MujocoContext does before mj_parseXMLString
    ref = mujoco.MjModel.from_xml_string(raw)
    os.chdir(cwd)
    model = mujoco.MjModel.from_xml_path(os.path.join(tmp, "scene.xml"))
    diffs, bad = compare_models(ref, model)
    if bad:
        sys.exit(f"standalone scene differs from circus's compiled model in: {bad}")
    print(f"exact: {len(diffs)} path-only fields differ ({', '.join(diffs) or 'none'}); {len(copied)} assets copied")

    with open(os.path.join(tmp, "scene_index.json"), "w") as f:
        json.dump(build_index(root, model, args.commit, args.scene_yaml), f, indent=1)
    render_reference(mujoco.MjModel.from_xml_path(os.path.join(tmp, "scene.xml")), os.path.join(tmp, "reference.png"))

    old = f"{out_dir}.old-{os.getpid()}"
    if os.path.exists(out_dir):
        os.rename(out_dir, old)
    os.rename(tmp, out_dir)
    shutil.rmtree(old, ignore_errors=True)
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
