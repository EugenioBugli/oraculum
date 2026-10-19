"""Functional check of the B2Viewer API in headless Chromium (SwiftShader, no GPU needed).

Usage: python api_check.py ROOT [--page b2_bundle/index.html] [--scene ../b2_scenes/maximus_5v5]
       [--scene2 ../b2_scenes/maximus_1v1] [--out result.json]
ROOT is served over HTTP. Checks: no unimplemented/unsupported GL call at load, robots from
scene_index.json, setRobotState / setJoints / setBall / setNumber / setRobotVisible change the image
where project() says and undo exactly, camera helpers and pointer controls, WebGL context loss and
restore (same image after), load() of a second scene, MSAA samples, the 2048 px texture limit on
touch devices, and the B2_NO_WEBGL2 error. Exit 1 if a check fails.
"""
import argparse
import json
import sys

from playwright.sync_api import sync_playwright

from shot import READY, SWIFTSHADER, serve

# ImageData helpers in the page: snapshot -> {w, h, data}; pixel diff count and max at a point
JS_HELPERS = """
window.grab = () => { b2.render(); const c = b2.canvas, g = b2.gl, px = new Uint8Array(c.width * c.height * 4);
  g.readPixels(0, 0, c.width, c.height, g.RGBA, g.UNSIGNED_BYTE, px); return {w: c.width, h: c.height, px}; };
window.ndiff = (a, b) => { let n = 0; for (let i = 0; i < a.px.length; i += 4)
  if (a.px[i] !== b.px[i] || a.px[i + 1] !== b.px[i + 1] || a.px[i + 2] !== b.px[i + 2]) n++; return n; };
window.diffAt = (a, b, x, y) => { x = Math.round(x); y = Math.round(a.h - 1 - y); let m = 0;  // y: top-left origin
  for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const i = ((y + dy) * a.w + x + dx) * 4;
    for (let c = 0; c < 3; c++) m = Math.max(m, Math.abs(a.px[i + c] - b.px[i + c])); } return m; };
"""


def run(a):
    checks = {}

    def check(name, ok, info=None):
        checks[name] = {"ok": bool(ok), "info": info}
        print(("ok   " if ok else "FAIL ") + name + ("" if info is None else f"  {info}"), flush=True)

    srv = serve(a.root)
    base = f"http://127.0.0.1:{srv.server_port}/{a.page}"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=SWIFTSHADER)
        page = browser.new_page(viewport={"width": 1000, "height": 700})
        logs = []
        page.on("console", lambda m: logs.append(m.text))
        page.goto(f"{base}?w=640&h=360&aa=0&scene={a.scene}")
        page.wait_for_function(READY, timeout=300000, polling=200)
        if not page.evaluate("window.b2Ready"):
            check("page loads", False, logs[-10:])
            return checks
        ev = page.evaluate

        def do(js):  # run statements; return nothing (a function or big array result would be called / copied)
            page.evaluate(f"{{ {js} }}; 0")

        do(JS_HELPERS)
        check("no unimplemented GL call at load", ev("b2.unimplementedAtLoad") == 0, ev("b2.unimplementedAtLoad"))
        robots = ev("b2.listRobots()")
        check("robots from scene_index.json", len(robots) > 0, [r["name"] for r in robots][:3] + ["..."])
        r0 = robots[0]["name"]
        do("window.A = grab()")

        # visibility: all robots hidden, then shown again -> same image
        do("for (const r of b2.listRobots()) b2.setRobotVisible(r.name, false); window.B = grab()")
        check("setRobotVisible(false) hides robots", ev("ndiff(A, B)") > 1000, ev("ndiff(A, B)"))
        do("for (const r of b2.listRobots()) b2.setRobotVisible(r.name, true); window.C = grab()")
        check("setRobotVisible(true) restores the exact image", ev("ndiff(A, C)") == 0, ev("ndiff(A, C)"))

        # ball: project() of the ball centre lands on the ball
        do("b2.setBall(1.5, 0.8); window.D = grab(); b2.setBallVisible(false); window.E = grab(); b2.setBallVisible(true)")
        pt = ev("b2.project(1.5, 0.8, b2.ball.radius)")
        far = [pt[0] + 40, pt[1]]
        check("project() + setBall: ball pixels at the projected centre",
              ev(f"diffAt(D, E, {pt[0]}, {pt[1]})") > 30 and ev(f"diffAt(D, E, {far[0]}, {far[1]})") == 0,
              {"px": [round(v, 1) for v in pt], "radius_m": ev("b2.ball.radius")})
        vp = ev("(() => { const v = b2.getViewProjection(); return {w: v.width, h: v.height,"
                " nonzero: Array.from(v.viewProj).some((x) => x !== 0)}; })()")
        check("getViewProjection() size and matrices", vp == {"w": 640, "h": 360, "nonzero": True}, vp)

        # robot state and joints
        do(f"b2.setRobotState('{r0}', {{x: 0, y: 0, yaw: 1.0}}); window.F = grab();"
           f" b2.setRobotVisible('{r0}', false); window.G = grab(); b2.setRobotVisible('{r0}', true)")
        c = ev("b2.project(0, 0, 0.45)")
        check("setRobotState moves the robot to (0, 0)", ev(f"diffAt(F, G, {c[0]}, {c[1]})") > 10, [round(v, 1) for v in c])
        n = ev(f"b2.setJoints('{r0}', {{Left_Shoulder_Pitch: -1.5, Right_Shoulder_Pitch: -1.5, AAHead_yaw: 0.8, nope: 1}})")
        do("window.H = grab()")
        check("setJoints sets known joints and changes the image", n == 3 and ev("ndiff(F, H)") > 10, {"set": n, "px": ev("ndiff(F, H)")})

        # jersey number
        own = robots[0]["number"]
        do(f"b2.setNumber('{r0}', {own % 9 + 1}); window.I = grab(); b2.setNumber('{r0}', {own}); window.J = grab()")
        check("setNumber changes the number and back exactly", ev("ndiff(H, I)") > 0 and ev("ndiff(H, J)") == 0,
              {"px": ev("ndiff(H, I)"), "back": ev("ndiff(H, J)")})

        # camera helpers
        cam0 = ev("b2.getCamera()")
        check("default camera = circus viewport", cam0 == {"lookat": [0, -1, 0], "distance": 15, "azimuth": 90, "elevation": -45}, cam0)
        do("b2.orbit(0.1, 0); b2.zoom(2); b2.pan(0.1, 0)")
        cam1 = ev("b2.getCamera()")
        check("orbit / zoom / pan", abs(cam1["azimuth"] - 72) < 1e-9 and abs(cam1["distance"] - 7.5) < 1e-9
              and cam1["lookat"] != [0, -1, 0], cam1)
        do("b2.resetCamera()")

        # pointer controls (attachControls in index.html): mouse wheel, touch rotate, pinch
        box = page.locator("canvas").bounding_box()
        page.mouse.move(box["x"] + 300, box["y"] + 150)
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(100)
        d_wheel = ev("b2.getCamera().distance")
        do("""(() => { const c = b2.canvas, r = c.getBoundingClientRect();
          const pe = (t, id, x, y) => c.dispatchEvent(new PointerEvent(t, {pointerId: id, pointerType: 'touch',
            clientX: r.left + x, clientY: r.top + y, bubbles: true}));
          pe('pointerdown', 7, 100, 100); pe('pointermove', 7, 200, 100); pe('pointerup', 7, 200, 100);
          window.azTouch = b2.getCamera().azimuth;
          pe('pointerdown', 8, 100, 100); pe('pointerdown', 9, 200, 100);
          pe('pointermove', 9, 300, 100); pe('pointerup', 9, 300, 100); pe('pointerup', 8, 100, 100); })()""")
        cam2 = ev("b2.getCamera()")
        check("controls: wheel zooms in, one finger rotates, pinch zooms",
              d_wheel < 15 and abs(ev("azTouch") - (90 - 0.3 * 180)) < 1e-6 and cam2["distance"] < d_wheel,
              {"wheel_distance": d_wheel, "touch_azimuth": ev("azTouch"), "pinch_distance": cam2["distance"]})
        do("b2.resetCamera()")

        # context loss and restore: hidden robot and number survive, same image
        do(f"b2.setRobotVisible('{robots[1]['name']}', false); b2.setNumber('{r0}', 9); window.K = grab()")
        do("""window.restored = false; b2.canvas.addEventListener('b2restored', () => { window.restored = true; });
              window.LC = b2.gl.getExtension('WEBGL_lose_context'); LC.loseContext()""")
        page.wait_for_function("b2.lost", timeout=10000)
        check("render() returns null while the context is lost", ev("b2.render()") is None)
        do("LC.restoreContext()")
        page.wait_for_function("window.restored", timeout=300000, polling=200)
        do("window.L = grab()")
        check("context restore: same image (pose, camera, hidden robot, number kept)", ev("ndiff(K, L)") == 0, ev("ndiff(K, L)"))

        # runtime load of another scene and back
        if a.scene2:
            do(f"b2.load('{a.scene2}').then(() => {{ window.n2 = b2.listRobots().length; b2.render(); }})")
            page.wait_for_function("window.n2 !== undefined", timeout=300000, polling=200)
            n2 = ev("n2")
            do(f"window.n2 = undefined; b2.load('{a.scene}').then(() => {{ window.n2 = b2.listRobots().length; }})")
            page.wait_for_function("window.n2 !== undefined", timeout=300000, polling=200)
            do("window.M2 = grab()")
            check("load() switches scenes at run time", n2 != len(robots) and ev("n2") == len(robots)
                  and ev("ndiff(A, M2)") == 0, {"robots_scene2": n2, "diff_back": ev("ndiff(A, M2)")})
        check("no unimplemented/unsupported GL call (load + frames)",
              ev("b2.glUnimplemented") == 0 and ev("b2.glUnsupported") == 0, ev("b2.glIssues"))
        page.close()

        # MSAA
        page = browser.new_page()
        page.goto(f"{base}?w=320&h=180&aa=1&scene={a.scene}")
        page.wait_for_function(READY, timeout=300000, polling=200)
        check("antialias: multisampled drawing buffer", page.evaluate("b2.antialias && b2.samples >= 4"),
              page.evaluate("b2.samples"))
        page.close()

        # touch device: 2048 px texture limit by default
        ctx = browser.new_context(has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844})
        page = ctx.new_page()
        tlogs = []
        page.on("console", lambda m: tlogs.append(m.text))
        page.goto(f"{base}?w=390&h=220&scene={a.scene}")
        page.wait_for_function(READY, timeout=300000, polling=200)
        big = [t for t in tlogs if "decoded by the browser" in t]
        check("coarse pointer: maxTexture 2048 by default", page.evaluate("b2.maxTexture") == 2048
              and all("4096x" not in t for t in big), big[-1:] if big else None)
        ctx.close()

        # no WebGL2
        page = browser.new_page()
        page.add_init_script("const g = HTMLCanvasElement.prototype.getContext;"
                             "HTMLCanvasElement.prototype.getContext = function (t, o) {"
                             " return t === 'webgl2' ? null : g.call(this, t, o); };")
        page.goto(f"{base}?scene={a.scene}")
        page.wait_for_function(READY, timeout=60000)
        check("no WebGL2: error code B2_NO_WEBGL2", page.evaluate("window.b2Error") == "B2_NO_WEBGL2",
              page.evaluate("window.b2Error"))
        browser.close()
    srv.shutdown()
    return checks


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--page", default="b2_bundle/index.html")
    ap.add_argument("--scene", default="../b2_scenes/maximus_5v5")
    ap.add_argument("--scene2", default="../b2_scenes/maximus_1v1", help="empty: skip the scene switch")
    ap.add_argument("--out")
    args = ap.parse_args()
    result = run(args)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(result, f, indent=1)
    failed = [k for k, v in result.items() if not v["ok"]]
    print(f"{len(result) - len(failed)} of {len(result)} checks passed" + (f"; failed: {failed}" if failed else ""))
    sys.exit(1 if failed or not result else 0)
