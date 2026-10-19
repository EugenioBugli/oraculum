"""Browser renders of the B2 bundle (headless Chromium) and pixel comparison with native references.

Usage: python shot.py ROOT POSES.json REF_DIR OUT_DIR [--page b2_bundle/index.html]
       [--scene ../b2_scenes/maximus_5v5] [--sizes 1280x720 780x780] [--depth auto] [--aa 0]
       [--gpu]  (default: SwiftShader software WebGL; --gpu: system Chrome with ANGLE on the GPU)
ROOT is served over HTTP; --page and --scene are relative to it and to the page. The poses are set
from POSES.json directly (qpos arrays). For every pose and size: OUT_DIR/<pose>_<W>x<H>_browser.png,
_diff.png, _side_by_side.png and a row in OUT_DIR/metrics.json (PSNR, mean abs diff, % pixels with a
channel diff > 16, % of the reference's white line pixels kept). The reference of a render is
REF_DIR/<--ref-pattern>. With several patterns (the MSAA references of two GPUs), a render passes when it is
within the bounds against one of them; the row shows the nearer one (best PSNR) and all of them in by_ref.
--scene-sha256 FILE: the scene package must have this hash (compare.scene_sha256), else exit 4.

Exit codes: 0 = all renders within --min-psnr / --max-pct16 / --min-line-keep (when given), 3 = a render
out of bounds (the pixel test failed), 4 = the references were made from another scene ("reference out of
date": run msaa_refs.py), 2 = any other failure (page error, no reference, depth mode not the one asked
for, unimplemented or unsupported GL calls at load or render time).
"""
import argparse
import base64
import functools
import http.server
import json
import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright

from compare import compare, scene_sha256

SWIFTSHADER = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]
GPU = ["--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist", "--enable-gpu"]
READY = "window.b2Ready || window.b2Error"


def serve(root):
    http.server.SimpleHTTPRequestHandler.extensions_map[".wasm"] = "application/wasm"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(a):
    os.makedirs(a.out_dir, exist_ok=True)
    poses = json.load(open(a.poses))["poses"]
    sizes = [tuple(int(v) for v in s.split("x")) for s in a.sizes]
    srv = serve(a.root)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome" if a.gpu else None, args=GPU if a.gpu else SWIFTSHADER)
        for W, H in sizes:
            page = browser.new_page(viewport={"width": max(W, 800) + 40, "height": H + 200})
            logs = []
            page.on("console", lambda msg, logs=logs: logs.append(msg.text))
            page.on("pageerror", lambda err, logs=logs: logs.append("PAGEERROR " + str(err)))
            t0 = time.time()
            page.goto(f"http://127.0.0.1:{srv.server_port}/{a.page}?w={W}&h={H}&depth={a.depth}&aa={a.aa}"
                      f"&scene={a.scene}&preserve{a.query}")
            page.wait_for_function(READY, timeout=300000, polling=200)
            res = {"size": f"{W}x{H}", "load_s": round(time.time() - t0, 2), "requested_depth": a.depth,
                   "renderer": page.evaluate(
                       "(() => { const g = document.createElement('canvas').getContext('webgl2');"
                       " const e = g && g.getExtension('WEBGL_debug_renderer_info');"
                       " return e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : null; })()")}
            if not page.evaluate("window.b2Ready"):
                res["error"] = logs[-20:]
                results.append(res)
                print(json.dumps(res), flush=True)
                continue
            res.update(page.evaluate("({depth: b2.depthMode, samples: b2.samples, antialias: b2.antialias,"
                                     " unimplemented_at_load: b2.unimplementedAtLoad})"))
            if a.depth != "auto" and res["depth"] != a.depth:
                res["error"] = f"depth mode {res['depth']} instead of {a.depth} (EXT_clip_control missing?)"
            for pose in poses:
                page.evaluate("q => b2SetPose(q)", pose["qpos"])
                url = page.evaluate("b2Snapshot()")
                name = f"{pose['name']}_{W}x{H}"
                png = os.path.join(a.out_dir, f"{name}_browser.png")
                with open(png, "wb") as f:
                    f.write(base64.b64decode(url.split(",", 1)[1]))
                row = {"pose": pose["name"], "size": f"{W}x{H}", "depth": res["depth"], "samples": res["samples"],
                       "stats": page.evaluate("b2.stats")}
                refs = [os.path.join(a.ref_dir, r.format(pose=pose["name"], size=f"{W}x{H}")) for r in a.ref_pattern]
                missing = [r for r in refs if not os.path.exists(r)]
                if missing:
                    row["error"] = f"no reference {missing}"
                else:
                    tag = (lambda r: "_" + os.path.basename(r)[:-4]) if len(refs) > 1 else (lambda r: "")
                    by_ref = [dict(compare(r, png, os.path.join(a.out_dir, name + tag(r))), ref=os.path.basename(r))
                              for r in refs]
                    row.update(max(by_ref, key=lambda m: m["psnr_db"]))
                    if len(by_ref) > 1:
                        row["by_ref"] = by_ref
                results.append(row)
                print(json.dumps(row), flush=True)
            if a.timing:
                res["fps_raf_3s"] = round(page.evaluate("spikeFps(3000)"), 2)
                res["ms_per_frame_sync"] = round(page.evaluate("b2Bench(10)"), 2)
            res["gl_unimplemented"] = page.evaluate("b2.glUnimplemented")
            res["gl_unsupported"] = page.evaluate("b2.glUnsupported")
            res["gl_issues"] = page.evaluate("b2.glIssues")
            res["console"] = logs[-30:]
            results.append(res)
            print(json.dumps({k: v for k, v in res.items() if k != "console"}), flush=True)
            page.close()
        browser.close()
    srv.shutdown()
    with open(os.path.join(a.out_dir, "metrics.json"), "w") as f:
        json.dump(results, f, indent=1)
    return results


def verdict(rows, min_psnr, max_pct16, min_line_keep=None):
    """(exit code, message) for the rows of main()."""
    errors = [r for r in rows if "error" in r]
    gl = sum(r.get("gl_unimplemented", 0) + r.get("gl_unsupported", 0) for r in rows)
    if errors or gl:
        return 2, f"{len(errors)} errors, {gl} unimplemented/unsupported GL calls: " + json.dumps(
            [r.get("error") for r in errors] + [r.get("gl_issues") for r in rows if r.get("gl_issues")])[:2000]
    scored = [r for r in rows if "psnr_db" in r]
    if not scored:
        return 2, "no render was compared"
    def within(m):
        return not ((min_psnr is not None and m["psnr_db"] < min_psnr)
                    or (max_pct16 is not None and m["pct_pixels_diff_gt_16"] >= max_pct16)
                    or (min_line_keep is not None and m["line_keep_pct"] < min_line_keep))
    bad = [r for r in scored if not any(within(m) for m in r.get("by_ref", [r]))]
    worst = min(scored, key=lambda r: r["psnr_db"])
    msg = (f"{len(bad)} of {len(scored)} renders out of bounds; worst {worst['pose']} {worst['size']}: "
           f"{worst['psnr_db']} dB, {worst['pct_pixels_diff_gt_16']} % px > 16; "
           f"least line pixels kept: {min(max(m['line_keep_pct'] for m in r.get('by_ref', [r])) for r in scored)} %")
    return (3 if bad else 0), msg


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="folder served over HTTP (holds the page and the scenes)")
    ap.add_argument("poses")
    ap.add_argument("ref_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--page", default="b2_bundle/index.html")
    ap.add_argument("--scene", default="../b2_scenes/maximus_5v5", help="scene package URL, relative to the page")
    ap.add_argument("--sizes", nargs="+", default=["1280x720", "780x780"])
    ap.add_argument("--depth", default="auto")
    ap.add_argument("--aa", default="0", help="1 = WebGL antialias (MSAA), 0 = off")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--timing", action="store_true", help="also measure fps and ms per frame")
    ap.add_argument("--query", default="", help="extra URL parameters, e.g. &maxtex=2048")
    ap.add_argument("--ref-pattern", nargs="+", default=["{pose}_{size}_reference.png"])
    ap.add_argument("--min-psnr", type=float, help="exit 3 if a render scores below this PSNR (dB)")
    ap.add_argument("--max-pct16", type=float, help="exit 3 if this % of pixels or more differ by > 16")
    ap.add_argument("--min-line-keep", type=float, help="exit 3 if a render keeps less than this % of the line pixels")
    ap.add_argument("--scene-sha256", help="file with the scene hash the references were made from")
    args = ap.parse_args()
    if args.scene_sha256:
        want = open(args.scene_sha256).read().strip()
        have = scene_sha256(os.path.normpath(os.path.join(args.root, os.path.dirname(args.page), args.scene)))
        if have != want:
            print(f"FAIL reference out of date: the scene has sha256 {have}, the references in {args.ref_dir} were "
                  f"made from {want}. Make new ones with renderer/msaa_refs.py on a machine with GPUs and commit them.")
            sys.exit(4)
    code, message = verdict(main(args), args.min_psnr, args.max_pct16, args.min_line_keep)
    print(("PASS " if code == 0 else "FAIL ") + message, flush=True)
    sys.exit(code)
