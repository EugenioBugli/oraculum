"""Browser test of the robot command panel (index.html, dashboard.html). Gateway on :8080 + tools/udp_sender.py must run.
/stop, /goto and /positions are answered here (mocked); /state is patched: robot 2 is in match mode, a sent go-to shows as
agent.goto. Usage: python3 tools/panel_check.py <outdir for screenshots and the video>"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://localhost:8080"
POS = {"positions": [
    {"id": "ready_1", "label": "Ready R1", "x": -1.0, "y": 0.0, "theta": 0.0, "player": 1},
    {"id": "ready_3", "label": "Ready R3", "x": -3.0, "y": 2.0, "theta": 0.0, "player": 3},
    {"id": "sideline_1", "label": "Side line R1", "x": -2.0, "y": -7.0, "theta": 1.57, "player": 1},
    {"id": "sideline_3", "label": "Side line R3", "x": -4.0, "y": -7.0, "theta": 1.57, "player": 3},
]}
ERR = {403: "Referee rule: no manual command in PLAYING", 409: "This robot is in match mode", 423: "Dana has control. Ask for it first."}
log, mode, goto = [], {"status": 200}, {}
errors, fails = [], []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def handle(route):
    req = route.request
    path = req.url.split("8080", 1)[1].split("?")[0]
    if path == "/positions":  # ?robot=<ip>: the shared field frame for that robot's team
        return route.fulfill(json={**POS, "frame": "field" if "robot=" in req.url else "team"})
    if path == "/state":
        try:
            s = route.fetch().json()
        except Exception:  # the context closed while a poll was on its way
            return
        for a in s["agents"]:
            if a["id"] == 2:
                a.setdefault("sys", {})["link"] = "telemetry"
            if a["id"] in goto:
                a["goto"], a["latch"] = goto[a["id"]], "goto" if goto[a["id"]] else "getup"
        return route.fulfill(json=s)
    body = json.loads(req.post_data or "{}")
    log.append((path, body))
    st = mode["status"]
    if st != 200:
        return route.fulfill(status=st, json={"error": ERR[st]})
    if path == "/goto":  # {robot, pos} -> the target in the shared frame; {robot, cancel} -> stands still (latch getup)
        rid = 3  # the test drives robot 3
        p = next((q for q in POS["positions"] if q["id"] == body.get("pos")), None)
        if not body.get("cancel") and not p:
            return route.fulfill(status=400, json={"error": "unknown position"})
        goto[rid] = None if body.get("cancel") else {k: p[k] for k in ("x", "y", "theta")}
        return route.fulfill(json={"status": "sent", "target": goto[rid], "pos": body.get("pos"), "targets": [body["robot"]], "names": [f"T? R3 ({body['robot']})"]})
    return route.fulfill(json={"status": "sent", "targets": [body.get("robot")], "names": [f"T? R? ({body.get('robot')})"]})


def toast(page):
    page.wait_for_selector(".ctl-toast:not([hidden])", timeout=3000)
    t = page.inner_text(".ctl-toast")
    page.evaluate("document.querySelector('.ctl-toast').hidden = true")
    return t


def hold(page, loc, ms):
    box = loc.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.wait_for_timeout(ms)
    page.mouse.up()


def item(page, rid):
    return page.locator(".robot-item").filter(has=page.locator(".robot-id", has_text=f"R{rid}")).first


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True,
                           args=["--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist", "--enable-gpu"])
    # --- main run, desktop, recorded ---
    ctx = br.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=OUT, record_video_size={"width": 1280, "height": 720})
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/{stop,goto,positions,state}*", handle)
    page.goto(f"{BASE}/index.html")
    page.wait_for_selector(".robot-item")
    check(not page.locator("#joyBoundary").is_visible() and page.locator(".rp-empty").is_visible(), "index: no joystick before a selection")
    check(not page.locator("#checkManualMode").is_visible(), "index: no MANUAL toggle before a selection")
    page.screenshot(path=f"{OUT}/index_1920_before.png")
    item(page, 3).click()
    page.wait_for_timeout(300)
    check(page.locator("#joyBoundary").is_visible(), "index: joystick after selecting R3")
    knob = page.evaluate("(() => { const k = document.getElementById('joyStick'), b = document.getElementById('joyBoundary'); return [k.offsetLeft + k.offsetWidth / 2, b.clientWidth / 2]; })()")
    check(abs(knob[0] - knob[1]) < 2, f"index: joystick knob centred {knob}")
    check("R3" in page.inner_text(".rp-name"), "index: panel names R3: " + page.inner_text(".rp-name"))
    # miniature: 3D (WebGL2) and moving with the fake joints
    page.wait_for_function("document.querySelector('.rp-mini') && performance.now() > 0", timeout=5000)
    t0 = time.time()
    shots = []
    while time.time() - t0 < 60:
        page.wait_for_timeout(500)
        shots.append(page.locator(".rp-mini").screenshot())
        if len(shots) >= 2 and shots[-1] != shots[-2] and len(set(shots[-2:])) == 2 and len(shots) > 3:
            break
    gl = page.evaluate("(() => { const c = document.querySelector('.rp-mini'); return !!(c.getContext('webgl2')); })()")
    check(gl, "index: miniature is a WebGL2 canvas (not the 2D icon)")
    a, b = page.locator(".rp-mini").screenshot(), (page.wait_for_timeout(500), page.locator(".rp-mini").screenshot())[1]
    check(a != b, "index: miniature changes between two frames 0.5 s apart (joints move)")
    open(f"{OUT}/mini_a.png", "wb").write(a)
    open(f"{OUT}/mini_b.png", "wb").write(b)
    # goto options: R3's own positions first
    groups = page.eval_on_selector(".rp-goto select", "s => [...s.querySelectorAll('optgroup')].map(g => g.label + ':' + [...g.children].map(o => o.value).join(','))")
    check(groups == ["R3:ready_3,sideline_3", "Other positions:ready_1,sideline_1"], f"index: positions sorted {groups}")
    page.screenshot(path=f"{OUT}/index_1920_selected.png")
    # every button
    cmds = page.locator(".rp-cmds")
    for text, want in [("STOP", ("stop", None)), ("Resume", ("resume", None)), ("Get up", ("getup", None))]:
        btn = cmds.locator("button", has_text=text).first
        check("R3" in btn.inner_text(), f"button names its robot: {btn.inner_text()!r}")
        n = len(log)
        btn.click()
        t = toast(page)
        check(len(log) == n + 1 and log[-1][0] == "/stop" and log[-1][1]["kind"] == want[0] and log[-1][1]["robot"] == "127.0.0.1",
              f"{text} -> POST /stop kind={want[0]} ({log[-1][1] if len(log) > n else 'nothing'}); toast {t!r}")
    n = len(log)
    hold(page, cmds.locator("button.ctl-hold", has_text="LIE DOWN"), 600)
    page.wait_for_timeout(300)
    check(len(log) == n, "LIE DOWN: a 0.6 s press sends nothing")
    hold(page, cmds.locator("button.ctl-hold", has_text="LIE DOWN"), 2300)
    t = toast(page)
    check(len(log) == n + 1 and log[-1][1]["kind"] == "lie", f"LIE DOWN 2 s hold -> kind=lie; toast {t!r}")
    page.select_option(".rp-goto select", "sideline_3")
    cmds.locator("button", has_text="Go").first.click()
    t = toast(page)
    check(log[-1][0] == "/goto" and log[-1][1].get("pos") == "sideline_3" and "x" not in log[-1][1] and log[-1][1].get("name") and "client" in log[-1][1],
          f"Go -> POST /goto {log[-1][1]}; toast {t!r}")
    page.wait_for_timeout(600)
    check("Side line R3" in page.inner_text(".rp-info"), "panel shows the go-to target: " + page.inner_text(".rp-info").replace("\n", " | "))
    page.screenshot(path=f"{OUT}/index_1920_goto.png")
    page.locator(".v-tab[data-mode='2d']").click()
    page.wait_for_timeout(600)
    page.screenshot(path=f"{OUT}/index_1920_goto_2d.png")
    page.locator(".v-tab[data-mode='3d']").click()
    cmds.locator("button", has_text="Cancel").first.click()
    t = toast(page)
    check(log[-1] == ("/goto", {**log[-1][1], "cancel": True}) and log[-1][1]["robot"] == "127.0.0.1", f"Cancel -> POST /goto cancel {log[-1][1]}; toast {t!r}")
    page.wait_for_timeout(600)
    check("GETTING UP" in page.inner_text(".rp-info"), "after Cancel the latch reads getup: " + page.inner_text(".rp-info").replace("\n", " | "))
    # DAMP: typed word + 3 s hold
    page.locator(".rp-cmds details summary").click()
    dbtn = page.locator(".rp-cmds details button")
    check(dbtn.is_disabled(), "DAMP disabled before the word is typed")
    page.locator(".rp-cmds details input").fill("R3")
    check(dbtn.is_enabled(), "DAMP enabled after typing R3")
    n = len(log)
    hold(page, dbtn, 3300)
    t = toast(page)
    check(len(log) == n + 1 and log[-1][1]["kind"] == "damp" and log[-1][1]["confirm"] == "127.0.0.1", f"DAMP hold 3 s -> kind=damp confirm=ip; toast {t!r}")
    # errors: 403, 409, 423 -> red toast with the gateway's text
    for st in (403, 409, 423):
        mode["status"] = st
        cmds.locator("button", has_text="Get up").first.click()
        t = toast(page)
        err = page.evaluate("document.querySelector('.ctl-toast').classList.contains('err')")
        check(err and t == ERR[st], f"HTTP {st} -> error toast {t!r}")
        cmds.locator("button", has_text="Go").first.click()
        t = toast(page)
        check(t == ERR[st], f"Go with HTTP {st} -> error toast {t!r}")
    mode["status"] = 200
    # bypass flag reaches the body
    # ticked and clicked in one task: without control, the next /state unticks the bypass (syncBypassRow)
    page.evaluate("document.getElementById('checkTestingOverride').checked = true; [...document.querySelectorAll('.rp-cmds button')].find(b => b.textContent.startsWith('Get up')).click()")
    toast(page)
    check(log[-1][1].get("testingOverride") is True, "bypass ticked -> testingOverride in the body")
    page.evaluate("setBypass(false)")
    # match-mode robot: new buttons disabled with a tooltip
    item(page, 2).click()
    page.wait_for_timeout(500)
    dis = page.eval_on_selector_all(".rp-cmds button", "bs => bs.map(b => [b.textContent.trim(), b.disabled, b.title.slice(0, 10)])")
    newb = [d for d in dis if d[0].split(" ")[0] in ("Get", "Sit", "Hold:", "LIE", "Go", "Cancel")]
    check(len(newb) == 4, f"match robot R2 (T1): 4 new buttons, no Sit down {len(newb)}")
    check(newb and all(d[1] and d[2] == "Match mode" for d in newb), f"match robot R2: new buttons disabled {newb}")
    check(page.locator(".rp-cmds details input").is_disabled(), "match robot R2: DAMP word input disabled")
    page.screenshot(path=f"{OUT}/index_1920_match.png")
    # Sit down: only a T2 (FAKE_MODELS=t2,t1,k1: R1 is a T2, R3 a K1)
    check(cmds.locator("button", has_text="Sit").count() == 0, "R3 (K1): no Sit down button")
    item(page, 1).click()
    page.wait_for_timeout(500)
    sit = cmds.locator("button", has_text="Sit down")
    check(sit.count() == 1 and "R1" in sit.inner_text(), "R1 (T2): Sit down button " + (sit.inner_text() if sit.count() else "missing"))
    n = len(log)
    sit.click()
    t = toast(page)
    check(len(log) == n + 1 and log[-1][1]["kind"] == "sit", f"Sit down -> POST /stop kind=sit; toast {t!r}")
    mode["status"] = 409
    ERR[409] = "Sit exists only on the T2"
    sit.click()
    check(toast(page) == ERR[409], "Sit down with 409 -> the gateway's toast")
    mode["status"] = 200
    item(page, 3).click()
    page.wait_for_timeout(1500)
    page.unroute_all(behavior="ignoreErrors")
    ctx.close()  # writes the video

    # --- layouts ---
    def layout(url, w, h, name, open_dock=False):
        c = br.new_context(viewport={"width": w, "height": h}, has_touch=w < 1000, is_mobile=w < 600)
        pg = c.new_page()
        pg.on("console", lambda m: m.type == "error" and errors.append(f"{name}: {m.text}"))
        pg.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
        pg.route("**/{stop,goto,positions,state}*", handle)
        pg.goto(BASE + url)
        pg.wait_for_selector(".robot-item", state="attached")
        if open_dock:
            pg.evaluate("document.getElementById('toolPanelDock').classList.remove('collapsed')")
        it = item(pg, 3)
        if not it.is_visible():
            pg.evaluate("toggleToolPanel && toggleToolPanel()")
        pg.evaluate("selectRobot(3, '127.0.0.1')")
        pg.wait_for_timeout(2500)
        pg.evaluate("document.getElementById('inspectorDock')?.classList.remove('collapsed')")
        pg.locator("#robotPanel").scroll_into_view_if_needed()
        pg.wait_for_timeout(800)
        sw = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        check(sw[0] <= sw[1], f"{name}: no horizontal page scroll {sw}")
        # every panel element inside the panel box, no button cut
        out = pg.evaluate("""(() => { const p = document.getElementById('robotPanel').getBoundingClientRect(), bad = [];
            for (const e of document.querySelectorAll('#robotPanel button, #robotPanel select, #robotPanel canvas, .rp-name')) {
                const r = e.getBoundingClientRect(); if (!r.width) continue;
                if (r.left < p.left - 1 || r.right > p.right + 1 || e.scrollWidth > e.clientWidth + 2) bad.push(e.textContent.trim() || e.tagName); }
            return bad; })()""")
        check(not out, f"{name}: no panel control cut or outside the panel {out}")
        pg.locator("#robotPanel").screenshot(path=f"{OUT}/{name}_panel.png")
        pg.screenshot(path=f"{OUT}/{name}.png")
        pg.unroute_all(behavior="ignoreErrors")
        c.close()

    layout("/index.html", 390, 844, "index_390x844")
    layout("/index.html", 820, 1180, "index_820x1180")
    layout("/index.html", 1920, 1080, "index_1920x1080")
    layout("/dashboard.html", 1920, 1080, "dashboard_1920x1080")
    layout("/dashboard.html", 1180, 820, "dashboard_1180x820")
    layout("/dashboard.html", 844, 390, "dashboard_844x390")
    br.close()

# the browser logs each mocked 403/409/423 reply as a failed resource: expected, not a page error
errors = [e for e in errors if not any(f"status of {c}" in e for c in (403, 409, 423))]
print("console errors:", errors or "none")
print("requests:", *[f"  {p} {json.dumps(b)}" for p, b in log], sep="\n")
print("FAILED:" if fails or errors else "ALL PASS", fails)
sys.exit(1 if fails or errors else 0)
