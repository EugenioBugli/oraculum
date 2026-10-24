"""Browser check of robots on other branches (src/reception.py): source tags and read-only command controls on fleet,
index, dashboard and robot pages. Needs the gateway on :8080 and
    python3 tools/udp_sender.py --hybrid --team-only 1 --gc-only 1
(debug robots of team 19 also send team messages: DBG+TM; T19 R9 from 127.0.0.2 sends only team messages: TM, read-only;
T5 R9 from 127.0.0.3 sends only GameController return packets: GC, read-only).
Every POST except /state polls is answered here and logged: nothing reaches a robot.
Usage: python3 tools/reception_check.py <outdir for screenshots>   (exit 0 = pass)"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else "."
BASE = "http://localhost:8080"
posts, errors, fails = [], [], []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def guard(route):
    if route.request.method == "POST":
        posts.append(route.request.url)
        return route.fulfill(status=200, json={"status": "caught by reception_check"})
    return route.continue_()


def buttons(page, sel):
    return page.eval_on_selector_all(sel + " button", "bs => bs.map(b => [b.textContent.trim(), b.disabled, b.title])")


os.makedirs(OUT, exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    ctx.route("**/*", guard)
    page = ctx.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))

    st = page.request.get(BASE + "/state").json()
    by = {(a["ip"], a["team"], a["id"]): a for a in st["agents"]}
    tm, gc = by.get(("127.0.0.2", 19, 9)), by.get(("127.0.0.3", 5, 9))
    check(tm and tm["readonly"] and tm["sources"] == ["team"] and tm["sys"]["link"] == "none", f"/state T19 R9 team-only: {tm and tm['sources']}")
    check(gc and gc["readonly"] and gc["sources"] == ["gc"], f"/state T5 R9 GC-only: {gc and gc['sources']}")
    hybrid = [a for a in st["agents"] if a["team"] == 19 and a["ip"] == "127.0.0.1"]
    check(hybrid and all(a["sources"] == ["debug", "team"] and not a["readonly"] for a in hybrid), "/state debug robots of team 19: debug+team")
    check(st["reception"]["teams"]["19"]["listening"] and st["reception"]["gc_return"]["listening"], "/state reception: 10019 and 3939 bound")

    # Fleet: tags, read-only rows disabled, debug rows enabled, the 0.6 s team-only robot not greyed as stale
    page.goto(BASE + "/fleet.html")
    page.wait_for_selector("#fleet tbody tr td[data-act] button")
    time.sleep(2.5)
    rows = page.eval_on_selector_all("#fleet tbody tr", """rs => rs.map(r => ({ key: r.dataset.key, tag: r.querySelector('.src-tag')?.textContent || '',
        stale: r.classList.contains('stale'), dis: [...r.querySelectorAll('td[data-act] button')].map(b => b.disabled) }))""")
    rk = {r["key"]: r for r in rows}
    ro = rk.get("127.0.0.2|9")
    check(ro and ro["tag"] == "TM · read-only" and ro["dis"] and all(ro["dis"]), f"fleet T19 R9: {ro}")
    g = rk.get("127.0.0.3|9")
    check(g and g["tag"] == "GC · read-only" and all(g["dis"]), f"fleet T5 R9: {g}")
    dbg = [r for k, r in rk.items() if k.startswith("127.0.0.1|")]
    check(dbg and all(not any(r["dis"]) for r in dbg) and {r["tag"] for r in dbg} <= {"DBG", "DBG+TM"} and any(r["tag"] == "DBG+TM" for r in dbg),
          f"fleet debug rows enabled, tags {sorted({r['tag'] for r in dbg})}")
    stale_seen = False
    for _ in range(6):  # 3 s of polls
        stale_seen |= page.eval_on_selector('#fleet tr[data-key="127.0.0.2|9"]', "r => r.classList.contains('stale')")
        time.sleep(0.5)
    check(not stale_seen, "fleet: the team-only robot (0.6 s messages) is never greyed as stale")
    title = page.get_attribute('#fleet tr[data-key="127.0.0.2|9"] td[data-act] button', "title")
    check("Read-only" in (title or ""), f"fleet read-only tooltip: {title!r}")
    page.screenshot(path=f"{OUT}/fleet.png", full_page=True)

    # Index and dashboard: tags in the robot list, card buttons, and the command panel of a selected read-only robot
    for name in ("index", "dashboard"):
        page.goto(f"{BASE}/{name}.html?mode=2d")
        page.wait_for_selector(".robot-item .src-tag")
        time.sleep(1.5)
        tags = page.eval_on_selector_all(".robot-item", "is => is.map(i => i.querySelector('.src-tag')?.textContent || '')")
        check("TM · read-only" in tags and "GC · read-only" in tags and "DBG+TM" in tags, f"{name}: list tags {sorted(set(tags))}")
        page.evaluate("selectRobot(9, '127.0.0.2')")
        time.sleep(1.5)
        panel = buttons(page, "#robotPanel .rp-cmds")
        check(panel and all(d for _, d, _ in panel), f"{name}: panel of the read-only robot, all {len(panel)} buttons disabled")
        warn = page.eval_on_selector("#robotPanel", "p => p.textContent.includes('read-only')")
        check(warn, f"{name}: panel says read-only")
        manual = page.eval_on_selector("#checkManualMode", "b => b.disabled")
        check(manual and "read-only" in page.inner_text("#manualTarget"), f"{name}: MANUAL disabled for the read-only robot")
        page.screenshot(path=f"{OUT}/{name}_readonly.png")
        first = next(a for a in hybrid)
        page.evaluate(f"selectRobot({first['id']}, '127.0.0.1')")
        time.sleep(1.5)
        panel = buttons(page, "#robotPanel .rp-cmds")
        stop = [d for t, d, _ in panel if t.startswith("STOP")]
        check(stop and not stop[0], f"{name}: panel of a debug robot, STOP enabled")
        check(not page.eval_on_selector("#checkManualMode", "b => b.disabled"), f"{name}: MANUAL enabled for a debug robot")
        tip = page.get_attribute("#budgetUsage", "title") or ""
        check("Team messages heard" in tip and "T19" in tip, f"{name}: budget tooltip has the per-team counts: {tip[-80:]!r}")
        cards = page.eval_on_selector_all(".robot-item", """is => is.map(i => [i.querySelector('.src-tag')?.textContent || '',
            [...i.querySelectorAll('.card-actions button')].map(b => b.disabled)])""")
        check(all(all(d) if "read-only" in t else not any(d) for t, d in cards), f"{name}: card buttons disabled exactly for read-only robots")
        page.screenshot(path=f"{OUT}/{name}_debug.png")

    # Robot page of the GC-only robot
    page.goto(f"{BASE}/robot.html?robot=127.0.0.3|9")
    page.wait_for_selector("#facts div")
    time.sleep(2)
    facts = page.inner_text("#facts")
    check("GC" in facts and "read-only" in facts, "robot page: Sources GC, read-only")
    acts = buttons(page, "#robotAct")
    check(acts and all(d for _, d, _ in acts), f"robot page: all {len(acts)} buttons disabled")
    page.screenshot(path=f"{OUT}/robot_gc_only.png", full_page=True)

    check(not posts, f"no command POST: {posts}")
    check(not errors, f"no page errors: {errors[:3]}")
    browser.close()

print("FAIL" if fails else "reception_check: all passed")
sys.exit(1 if fails else 0)
