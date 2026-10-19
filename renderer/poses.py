"""Posed states of the circus 5v5 scene for render tests (fixed seed).

Usage: python poses.py SCENE_DIR OUT.json [--seed 20261011]
Writes {"poses": [{"name", "qpos"}, ...]}: qpos0 plus pose1..pose3. Each pose moves and turns every
robot on the field (pose3 also lays some robots on the ground), sets every hinge joint uniformly
inside its range, and moves and spins the ball. Robot and ball addresses come from scene_index.json.
"""
import argparse
import json
import os

import mujoco
import numpy as np


def make_poses(scene_dir, seed, count=3, suffix=""):
    m = mujoco.MjModel.from_xml_path(os.path.join(scene_dir, "scene.xml"))
    index = json.load(open(os.path.join(scene_dir, "scene_index.json")))
    rng = np.random.default_rng(seed)
    poses = [{"name": "qpos0" + suffix, "qpos": m.qpos0.tolist()}]
    for k in range(1, count + 1):
        q = m.qpos0.copy()
        for robot in index["robots"]:
            a = robot["freejoint"]["qposadr"]
            fallen = k == 3 and rng.random() < 0.4
            roll, pitch = (rng.choice([-1, 1]) * np.pi / 2, 0.0) if fallen else rng.uniform(-0.15, 0.15, 2)
            quat = np.zeros(4)
            mujoco.mju_euler2Quat(quat, np.array([roll, pitch, rng.uniform(-np.pi, np.pi)]), "xyz")
            z = 0.18 if fallen else q[a + 2] + rng.uniform(-0.1, 0.02)
            q[a:a + 3] = [rng.uniform(-6.5, 6.5), rng.uniform(-4.2, 4.2), z]
            q[a + 3:a + 7] = quat
            for name, adr in robot["hinge_qposadr"].items():
                lo, hi = m.jnt_range[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, name)]
                q[adr] = rng.uniform(lo, hi)
        b = index["ball"]["freejoint"]["qposadr"]
        quat = rng.normal(size=4)
        q[b:b + 3] = [rng.uniform(-6, 6), rng.uniform(-4, 4), rng.uniform(0.12, 1.0)]
        q[b + 3:b + 7] = quat / np.linalg.norm(quat)
        poses.append({"name": f"pose{k}{suffix}", "qpos": [float(x) for x in q]})
    return {
        "scene": os.path.basename(os.path.normpath(scene_dir)),
        "circus_commit": index.get("circus_commit"),
        "mujoco_version": mujoco.__version__,
        "seed": seed,
        "nq": int(m.nq),
        "camera": {"lookat": [0, -1, 0], "distance": 15, "azimuth": 90, "elevation": -45},
        "note": "qpos layout: per free joint x y z qw qx qy qz (world frame), then hinges; see scene_index.json",
        "poses": poses,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scene_dir")
    ap.add_argument("out")
    ap.add_argument("--seed", type=int, default=20261011)
    ap.add_argument("--count", type=int, default=3, help="number of random poses after qpos0")
    ap.add_argument("--suffix", default="", help="appended to every pose name")
    a = ap.parse_args()
    data = make_poses(a.scene_dir, a.seed, a.count, a.suffix)
    assert all(len(p["qpos"]) == data["nq"] for p in data["poses"])
    with open(a.out, "w") as f:
        json.dump(data, f)
    print(a.out, [p["name"] for p in data["poses"]])
