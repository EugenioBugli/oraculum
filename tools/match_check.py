"""Browser check of match mode (gateway match switch): every page shows the "MATCH — no commands" chip and disables every
command control, also after a few /state polls; read-only pages (TV, director) still work; no page sends a command.
Needs: ORACULUM_MATCH=1 python3 src/control_server.py  +  FAKE_MODELS=t2,t1,k1 python3 tools/udp_sender.py
Usage: python3 tools/match_check.py <outdir for screenshots and the video>   (exit 0 = pass)"""
import sys

from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
BASE = "http://localhost:8080"
COMMANDS = ("/stop", "/goto", "/control", "/gc")
posts, errors, fails = [], [], []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def enabled_commands(page):
    """Command controls that are still enabled: [text or id]."""
    sel = (".ctl-stop, .ctl-act button, .ctl-act select, .ctl-danger input, .ctl-danger button, .ctl-ovl .btns button, "
           "#checkManualMode, #checkTestingOverride, .joystick-panel-grid input")  # COMMANDS of control_bar.js
    return page.evaluate("s => [...document.querySelectorAll(s)].filter(e => !e.disabled).map(e => e.id || e.textContent.trim())", sel)


def command_page(page, name):
    page.wait_for_selector(".ctl-match:not([hidden])", timeout=8000)
    chip = page.locator(".ctl-match").first
    check(chip.is_visible() and chip.inner_text() == "MATCH — no commands", f"{name}: chip {chip.inner_text()!r}")
    check("L285" in (chip.get_attribute("title") or ""), f"{name}: chip tooltip names the rule")
    n = page.locator(".ctl-stop").count()
    page.wait_for_timeout(2500)  # a few /state polls: no page code may re-enable a control
    left = enabled_commands(page)
    check(n >= 1 and not left, f"{name}: {n} STOP buttons, every command control disabled (enabled: {left})")
    stop = page.locator(".ctl-stopall").first
    check(stop.is_disabled() and "L285" in stop.get_attribute("title"), f"{name}: STOP ALL disabled with the rule as tooltip")


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True,
                           args=["--use-gl=angle", "--use-angle=gl-egl", "--ignore-gpu-blocklist", "--enable-gpu"])
    ctx = br.new_context(viewport={"width": 1600, "height": 900}, record_video_dir=OUT, record_video_size={"width": 1280, "height": 720})
    ctx.on("request", lambda r: r.method == "POST" and posts.append(r.url.split("8080", 1)[1].split("?")[0]))
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{BASE}/index.html?mode=2d")
    page.wait_for_selector(".robot-item")
    command_page(page, "index")
    page.locator(".robot-item").filter(has=page.locator(".robot-id", has_text="R1")).first.click()  # R1: a T2 (Sit down)
    page.wait_for_timeout(2500)
    left = enabled_commands(page)
    check(not left, f"index: robot panel of R1, every command disabled (enabled: {left})")
    check(page.locator(".rp-cmds button", has_text="Sit down").count() == 1, "index: R1 (T2) panel built (Sit down shown, disabled)")
    check(page.evaluate("getComputedStyle(document.querySelector('.joystick-panel-grid')).pointerEvents") == "none", "index: joystick takes no input")
    page.locator("#checkManualMode").click(force=True)
    check(not page.locator("#checkManualMode").is_checked(), "index: MANUAL cannot be ticked")
    page.locator(".rp-cmds button", has_text="Get up").first.click(force=True)
    page.wait_for_timeout(300)
    page.screenshot(path=f"{OUT}/index_match.png")
    page.locator("#robotPanel").screenshot(path=f"{OUT}/index_match_panel.png")

    page.goto(f"{BASE}/dashboard.html?mode=2d")
    page.wait_for_selector(".ctl-bar", state="attached")
    command_page(page, "dashboard")
    page.screenshot(path=f"{OUT}/dashboard_match.png")

    page.goto(f"{BASE}/fleet.html")
    page.wait_for_selector(".ctl-act")
    command_page(page, "fleet")
    page.screenshot(path=f"{OUT}/fleet_match.png")

    page.goto(f"{BASE}/robot.html?robot=1")
    page.wait_for_selector(".ctl-danger")
    command_page(page, "robot")
    page.locator(".ctl-danger summary").first.click()
    page.wait_for_timeout(300)
    check(page.locator(".ctl-danger input").first.is_disabled(), "robot: DAMP word input disabled")
    page.screenshot(path=f"{OUT}/robot_match.png")

    for path in ("tv.html", "director.html"):  # read-only pages: no chip, no error
        page.goto(f"{BASE}/{path}")
        page.wait_for_timeout(2500)
        check(page.locator(".ctl-match").count() == 0, f"{path}: read-only, no command bar")
        page.screenshot(path=f"{OUT}/{path.split('.')[0]}_match.png")
    ctx.close()
    br.close()

sent = [x for x in posts if x in COMMANDS]
check(not sent, f"no command POST from any page ({sent}); other POSTs: {sorted(set(posts) - set(COMMANDS))}")
check(not errors, f"no page errors {errors[:3]}")
print("ALL PASS" if not fails else f"FAILED {fails}")
sys.exit(1 if fails else 0)
