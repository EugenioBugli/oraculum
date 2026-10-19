"""fps of the B2 bundle on this machine's GPU (system Chrome, ANGLE on OpenGL ES/EGL).

Usage: python gpu_fps.py BASE_URL OUT.json [--sizes 1280x720 780x780] [--depth auto] [--shots DIR]
BASE_URL serves the bundle (index.html). The GPU is the one Chrome picks: Intel by default,
NVIDIA with __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia
__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json in the environment.
"""
import argparse
import base64
import json
import os

from playwright.sync_api import sync_playwright

ARGS = ["--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist", "--enable-gpu"]


def main(base, out, sizes, depth, shots, poses, query=""):
    res = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=ARGS)
        for W, H in sizes:
            pg = b.new_page(viewport={"width": max(W, 800) + 40, "height": H + 200})
            logs = []
            pg.on("console", lambda m, logs=logs: logs.append(m.text))
            pg.goto(f"{base}/index.html?w={W}&h={H}&depth={depth}&pose=pose1{query}", timeout=120000)
            pg.wait_for_function("window.b2Ready || /B2_ERROR/.test(document.getElementById('log').textContent)",
                                 timeout=180000)
            r = {"size": f"{W}x{H}", "requested_depth": depth,
                 "renderer": pg.evaluate("(() => { const g = b2.gl; const e = g.getExtension('WEBGL_debug_renderer_info');"
                                         " return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : null; })()")}
            if not pg.evaluate("window.b2Ready"):
                r["error"] = logs[-10:]
                res.append(r)
                print(json.dumps(r), flush=True)
                continue
            r["depth_mode"] = pg.evaluate("b2.depthMode")
            r["depth_bits"] = pg.evaluate("b2.gl.getParameter(b2.gl.DEPTH_BITS)")
            pg.evaluate("spikeFps(1000)")  # warm-up
            r["fps_raf_5s"] = round(pg.evaluate("spikeFps(5000)"), 2)
            r["ms_per_frame_sync"] = round(pg.evaluate("b2Bench(30)"), 2)
            r["ms_per_frame_queued"] = round(pg.evaluate("b2Throughput(120)"), 2)
            r["stats"] = pg.evaluate("b2.stats")
            if shots:
                for name in poses:
                    pg.evaluate(f"b2SetPose('{name}')")
                    url = pg.evaluate("b2Snapshot()")
                    with open(os.path.join(shots, f"{name}_{W}x{H}_browser.png"), "wb") as f:
                        f.write(base64.b64decode(url.split(",", 1)[1]))
            r["console"] = logs[:6]
            res.append(r)
            print(json.dumps(r), flush=True)
            pg.close()
        b.close()
    with open(out, "w") as f:
        json.dump(res, f, indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("out")
    ap.add_argument("--sizes", nargs="+", default=["1280x720", "780x780"])
    ap.add_argument("--depth", default="auto")
    ap.add_argument("--shots")
    ap.add_argument("--query", default="")
    ap.add_argument("--poses", nargs="*", default=["qpos0", "pose1", "pose2", "pose3"])
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    main(a.base, a.out, [tuple(int(v) for v in s.split("x")) for s in a.sizes], a.depth, a.shots, a.poses, a.query)
