"""Headless check of the WASM 3D renderer in the browser dashboards.

Opens a page on a running gateway in headless Chromium (Playwright), selects an engine
(circus = the exact circus image, default; wasm; threejs), waits, and reports console errors, page errors
and whether the 3D view drew anything. Exit code 0 = the 3D view shows a field and the engine loaded
(circus: B2 renderer ready with 0 unimplemented GL calls; wasm: the MuJoCo T1 model).
Every POST /control is answered here and never reaches the gateway or a robot.

    python3 run_oraculum.py &  python3 tools/udp_sender.py &
    python3 tools/wasm_check.py [--url http://127.0.0.1:8080/index.html?mode=3d] [--shot out.png]
"""

import argparse
import base64
import sys

from playwright.sync_api import sync_playwright

# SwiftShader gives WebGL2 without a GPU (CI, cloud, SSH sessions).
CHROME_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]

# Counts pixel colour classes of a PNG screenshot (decoded in the page, no Python image library).
PIXEL_STATS_JS = """async (b64) => {
  const bmp = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob());
  const c = new OffscreenCanvas(bmp.width, bmp.height); const g = c.getContext('2d'); g.drawImage(bmp, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let green = 0, dark = 0, other = 0;
  for (let i = 0; i < d.length; i += 4) {
    const r = d[i], gg = d[i+1], b = d[i+2];
    if (gg > r + 30 && gg > b + 30) green++; else if (r + gg + b < 60) dark++; else other++;
  }
  return {w: c.width, h: c.height, green, dark, other};
}"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/index.html?mode=3d")
    ap.add_argument("--engine", default="circus", choices=["circus", "wasm", "threejs"])
    ap.add_argument("--wait", type=float, default=8.0, help="seconds to let the page run")
    ap.add_argument("--shot", default="", help="save a screenshot to this path")
    ap.add_argument("--viewport", default="1280x800", help="WxH, e.g. 390x844 for a phone")
    ap.add_argument("--channel", default="chrome", help="'chrome' = system Google Chrome; '' = Playwright's own Chromium")
    args = ap.parse_args()
    vw, vh = (int(v) for v in args.viewport.split("x"))

    logs, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel or None, args=CHROME_ARGS)
        page = browser.new_page(viewport={"width": vw, "height": vh})
        page.route("**/control", lambda r: r.fulfill(status=200, content_type="application/json", body="{}"))
        page.on("console", lambda m: logs.append(f"[{m.type}] {m.text}"))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("requestfailed", lambda r: errors.append(f"request failed: {r.url} {r.failure}"))
        page.add_init_script(f"localStorage.setItem('oraculum_renderer_engine_v2', '{args.engine}')")
        page.goto(args.url, wait_until="load")
        page.wait_for_timeout(args.wait * 1000)
        gl = page.evaluate("""() => { const g = document.createElement('canvas').getContext('webgl2');
            return g ? g.getParameter(g.VERSION) + ' / ' + g.getParameter(g.RENDERER) : 'no webgl2'; }""")
        circus = page.evaluate("() => window.circusView ? {ready: window.circusView.viewer.ready, "
                               "gl_unimplemented: window.circusView.viewer.glUnimplemented} : null")
        view = page.locator("#circusContainer" if args.engine == "circus" else "#threejsContainer")
        png = view.screenshot() if view.count() and view.is_visible() else page.screenshot()
        stats = page.evaluate(PIXEL_STATS_JS, base64.b64encode(png).decode())
        if args.shot:
            page.screenshot(path=args.shot)
        browser.close()

    print("WebGL:", gl)
    for line in logs:
        print(line)
    for e in errors:
        print("[pageerror]", e)
    print("canvas:", stats)
    mujoco_ok = args.engine != "wasm" or any("MuJoCo T1 model ready" in line for line in logs)
    print("MuJoCo model loaded:", mujoco_ok)
    circus_ok = args.engine != "circus" or bool(circus and circus["ready"] and circus["gl_unimplemented"] == 0)
    print("circus renderer:", circus)
    ok = not errors and mujoco_ok and circus_ok and stats.get("green", 0) > 1000
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
