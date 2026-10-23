// STOP and engineer mode for every page (index, dashboard, fleet, robot).
// - mountControlBar(el, api): STOP ALL and the control lock (src/control_lock.py) in the page header.
// - robotActions(ip, api, {lie}): STOP, Resume and (only where asked) a 2 s press-and-hold LIE DOWN for one robot.
// - dangerDamp(ip, api, label): DAMP drops the robot and can break it: a closed "Danger" section, the robot's name
//   typed to unlock, then a 3 s press-and-hold. The gateway also refuses DAMP for "all" and without confirm.
// - stateUrl(api) / withOperator(body): every /state poll and /control body carries this tab's client id, so the
//   gateway knows who holds the lock and that the holder's page is still open.
// STOP, LIE DOWN and DAMP need no lock and pass the GameController rule (POST /stop). The gateway answers "sent": the robot
// does not confirm yet, so no button claims the robot stopped.

import { dampWord, shortName } from "./field_model.js";

const read = (store, key, make) => {
    try { let v = store.getItem(key); if (!v) { v = make(); store.setItem(key, v); } return v; } catch { return make(); }
};
export const operator = {
    client: read(sessionStorage, "oraculum_client", () => `tab-${crypto.getRandomValues(new Uint32Array(2)).join("")}`),
    name: read(localStorage, "oraculum_operator", () => `operator-${Math.random().toString(36).slice(2, 6)}`),
};
const base = api => typeof api === "function" ? api() : api;  // a page whose gateway address can change passes a function
export const stateUrl = api => `${base(api)}/state?client=${encodeURIComponent(operator.client)}`;
export const withOperator = body => ({ ...body, client: operator.client, operator: operator.name });

const STYLE = `
.ctl-bar { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; font: 600 12px var(--font, system-ui, sans-serif); }
.ctl-lock { display: inline-flex; align-items: center; gap: 6px; padding: 3px 8px; border-radius: 6px; white-space: nowrap;
    border: 1px solid var(--border-strong, #3b3f4a); color: var(--text-2, #9fa4b2); background: var(--bg-card, #24272e); }
.ctl-txt { white-space: nowrap; }
.ctl-nm { display: inline-block; vertical-align: bottom; max-width: 14ch; overflow: hidden; text-overflow: ellipsis; }  /* only names shorten */
@media (max-width: 700px), (max-height: 500px) { .hold-pre, .ctl-free-nm { display: none; } }  /* "Control: free" without the name on phones (title has it) */  /* "Hold: LIE DOWN" -> "LIE DOWN" on phones (still a 2 s hold) */
@media (max-width: 1400px) { .ctl-nm { max-width: 9ch; } }  /* two names (holder, bypass) leave room for the GC clock and score */
@media (max-width: 900px) { .ctl-bar { flex-wrap: nowrap; } }
@media (max-width: 700px) and (min-height: 501px) {  /* phones in portrait: "Bypass: name" on its own line, name kept */
    .ctl-bar:has(.ctl-bypass:not([hidden])) { flex-wrap: wrap; max-width: 100%; }
    :has(> .ctl-bar .ctl-bypass:not([hidden])) { max-width: 100%; min-width: 0; flex-shrink: 1; } }
@media (pointer: coarse) { .ctl-bar button, .ctl-act button { min-height: 40px; } }  /* touch targets */
.ctl-lock.mine { color: #10b981; border-color: #10b981; }
.ctl-bypass { padding: 2px 8px; border-radius: 6px; border: 2px solid #dc2626; background: transparent; color: #f87171; white-space: nowrap; }  /* an outline: not a second STOP ALL */
@media (max-width: 700px) { .ctl-bypass { display: inline-block; max-width: 14ch; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
    .ctl-bypass .ctl-on { display: none; } .ctl-bypass { max-width: none; } .ctl-bypass .ctl-nm { max-width: 16ch; } }  /* phones: "Bypass: Dana", the header stays two rows */
.ctl-bypass[hidden] { display: none; }
.ctl-bp-s { display: none; }
@media (max-height: 500px) {  /* phone landscape: "BP: name" keeps the one-row header, STOP ALL and Take stay on screen */
    .ctl-bypass .ctl-bp-l, .ctl-bypass .ctl-on { display: none; } .ctl-bypass .ctl-bp-s { display: inline; } .ctl-bypass .ctl-nm { max-width: 8ch; } }
.ctl-lock.ask { color: #f59e0b; border-color: #f59e0b; }
.ctl-bar button, .ctl-act button { font: 700 12px var(--font, system-ui, sans-serif); border-radius: 6px; padding: 4px 9px;
    border: 1px solid var(--border-strong, #3b3f4a); background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); cursor: pointer; }
.ctl-bar button:focus-visible, .ctl-act button:focus-visible { outline: 2px solid #f59e0b; outline-offset: 2px; }
.ctl-name { cursor: pointer; text-decoration: underline dotted; }
button.ctl-stop { background: #dc2626; border-color: #dc2626; color: #fff; letter-spacing: .04em; }
button.ctl-stopall { padding: 5px 14px; font-size: 13px; white-space: nowrap; }
button.ctl-stop.one { background: transparent; color: #f87171; border: 2px solid #dc2626; }  /* one robot: an outline, never a second STOP ALL */
.ctl-act button { white-space: nowrap; }
.ctl-act.named button { min-height: 40px; }
.ctl-act { display: inline-flex; gap: 4px; flex-wrap: wrap; }
button.ctl-hold { position: relative; overflow: hidden; color: #fbbf24; border-color: #78350f; }
button.ctl-hold.damp { color: #f87171; border-color: #7f1d1d; }
button.ctl-hold .fill { position: absolute; inset: 0 auto 0 0; width: 0; background: rgba(245, 158, 11, .4); }
button.ctl-hold.damp .fill { background: rgba(220, 38, 38, .45); }
button.ctl-hold span { position: relative; }
button.ctl-hold:disabled { opacity: .45; cursor: not-allowed; }
.ctl-danger { border: 1px solid #7f1d1d; border-radius: 8px; padding: 6px 10px; color: #fca5a5; font: 600 12px var(--font, system-ui, sans-serif); }
.ctl-danger summary { cursor: pointer; }
.ctl-danger p { margin: 6px 0; color: var(--text-2, #9fa4b2); font-weight: 500; }
.ctl-danger input { font: 600 12px var(--mono, monospace); padding: 4px 6px; border-radius: 6px; border: 1px solid #7f1d1d;
    background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); width: 10em; margin-right: 6px; }
.ctl-toast { position: fixed; bottom: 84px; left: 0; right: 0; margin: 0 auto; width: fit-content; z-index: 9999; max-width: min(92vw, 560px);
    padding: 8px 14px; border-radius: 8px; font: 600 13px var(--font, system-ui, sans-serif); color: #fff; background: #065f46;
    box-shadow: 0 6px 24px rgba(0,0,0,.4); }
.ctl-toast.err { background: #991b1b; }
@media (max-width: 600px), (max-height: 500px) { .ctl-toast { bottom: auto; top: 8px; } }  /* phones: over the header, not over the robot cards */
body > .ctl-toast { visibility: visible !important; }  /* also over a "turn your device" overlay that hides the page */
/* Floating, expandable overlays shown on every page (GameController + recording), bottom-left so they clear the STOP toast. */
.ctl-ovl { position: fixed; left: 12px; bottom: 12px; z-index: 9998; display: flex; flex-direction: column-reverse; gap: 8px; align-items: flex-start; }
.ctl-ovl .panel { background: var(--bg-card, #24272e); border: 1px solid var(--border-strong, #3b3f4a); border-radius: 10px;
    box-shadow: 0 6px 24px rgba(0,0,0,.4); overflow: hidden; min-width: 190px; font: 600 12px var(--font, system-ui, sans-serif); color: var(--text, #eceef2); }
.ctl-ovl .pill-row { display: flex; align-items: center; gap: 8px; padding: 7px 11px; cursor: pointer; user-select: none; }
.ctl-ovl .pill-row:hover { background: var(--bg-input, #2b2e37); }
.ctl-ovl .caret { margin-left: auto; color: var(--text-2, #9fa4b2); transition: transform .15s; }
.ctl-ovl .panel.open .caret { transform: rotate(180deg); }
.ctl-ovl .body { display: none; padding: 8px 10px; border-top: 1px solid var(--border, #2d3038); }
.ctl-ovl .panel.open .body { display: block; }
.ctl-ovl .btns { display: flex; flex-wrap: wrap; gap: 4px; }
.ctl-ovl button { font: 700 12px var(--font, system-ui, sans-serif); border-radius: 6px; padding: 4px 9px; min-height: 30px; cursor: pointer;
    border: 1px solid var(--border-strong, #3b3f4a); background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); }
.ctl-ovl button:focus-visible { outline: 2px solid var(--amber, #f59e0b); outline-offset: 2px; }
.ctl-ovl button[aria-pressed="true"] { background: var(--indigo, #6366f1); border-color: var(--indigo, #6366f1); }
.ctl-ovl .recpill { display: inline-flex; align-items: center; gap: 7px; color: var(--text-2, #9fa4b2); }
.ctl-ovl .recpill.on { color: var(--red, #ef4444); }
.ctl-ovl .dot2 { width: 10px; height: 10px; border-radius: 50%; background: currentColor; display: inline-block; }
.ctl-ovl .recpill.on .dot2 { animation: ctlblink 1s steps(2) infinite; }
@keyframes ctlblink { 50% { opacity: .25; } }
.ctl-ovl .info { color: var(--text-2, #9fa4b2); font-weight: 500; margin-top: 6px; font: 500 11px var(--mono, ui-monospace, monospace); }
@media (pointer: coarse) { .ctl-ovl button { min-height: 40px; } }
@media (max-width: 700px) { .ctl-ovl { left: 8px; } }
.ctl-ovl.right { left: auto; right: 12px; align-items: flex-end; }  /* robot.html: bottom-left holds the camera legend */
.ctl-ovl .ovl-fab, .ctl-ovl-space { display: none; }
body:has(#manualBanner:not([hidden])) .ctl-ovl { bottom: calc(var(--manual-h, 44px) + 12px); }  /* over the fixed MANUAL banner (--manual-h: its height) */
/* Phones: one small round button at the bottom right opens the Record and GC menus; names and checkboxes are on the left */
@media (max-width: 600px), (max-height: 500px) {
    .ctl-ovl, .ctl-ovl.right { bottom: 12px; left: auto; right: 8px; align-items: flex-end; }
    .ctl-ovl .ovl-fab { display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; padding: 0;
        border-radius: 50%; font-size: 18px; box-shadow: 0 4px 14px rgba(0,0,0,.5); }
    .ctl-ovl .ovl-fab.rec { color: var(--red, #ef4444); border-color: var(--red, #ef4444); }
    .ctl-ovl:not(.open) .panel { display: none; }
}
/* --ctl-ovl-h: the height the overlays take at the bottom of the window (set by mountOverlays). The page end gets this space,
   so the last row can scroll clear of the boxes; a page with a fixed layout (index, dashboard) reserves it in its own column. */
.ctl-ovl-space { display: block; height: var(--ctl-ovl-h, 0px); }
`;
let styled = false, toastEl = null, toastTimer = 0;
function style() {
    if (styled) return;
    styled = true;
    document.head.append(Object.assign(document.createElement("style"), { textContent: STYLE }));
}
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };

export function toast(text, error = false) {
    if (!toastEl) {
        toastEl = el("div", { className: "ctl-toast", role: "status" });
        toastEl.setAttribute("aria-live", "assertive");
        document.body.append(toastEl);
    }
    toastEl.textContent = text;
    toastEl.classList.toggle("err", error);
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, error ? 8000 : 2500);
}

async function post(api, path, body) {
    try {
        // body last: its own fields win (Stop recording sends the recording's name, not the operator's)
        const r = await fetch(`${base(api)}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify({ client: operator.client, name: operator.name, ...body }) });
        const j = await r.json().catch(() => ({}));
        return { ok: r.ok, status: r.status, ...j };
    } catch (e) {
        return { ok: false, status: 0, error: `oraculum not reachable (${e.message})` };
    }
}

const AFTER = { stop: "stands until Resume", lie: "lies down until Resume", damp: "has soft motors" };
export async function sendStop(api, robot, kind, extra = {}) {
    const r = await post(api, "/stop", { robot, kind, ...extra });
    const who = (r.names || r.targets || []).join(", ");  // "T19 R3 (127.0.0.1)"; robots behind one address share it
    const many = robot === "all" || (r.names || []).join().includes(",");
    if (r.ok) toast(`${kind === "lie" ? "LIE DOWN" : kind.toUpperCase()} sent to ${who}` +
                    (AFTER[kind] ? `: ${many ? "each robot" : "the robot"} ${AFTER[kind]}` : ""));
    else toast(r.error || `${kind.toUpperCase()} failed (HTTP ${r.status})`, true);
    return r;
}

// The header part: STOP ALL and the lock chip. Returns {update(state), take(), hasControl(), waiting(), holder(),
// locked(reply)}. opts.onDenied(): the holder kept control after our request (a page turns MANUAL off).
// opts.beforeRelease(): awaited before Release and Cancel are sent: a page turns MANUAL off and waits for its last
// /control request, so no joystick command takes the free lock again after the release.
export function mountControlBar(host, api, opts = {}) {
    style();
    let view = { holder: null }, lastLocked = 0;
    const lock = el("span", { className: "ctl-lock" });
    lock.setAttribute("aria-live", "polite");
    const stopAll = el("button", { className: "ctl-stop ctl-stopall", textContent: "STOP ALL",
                                   title: "Every robot heard in the last 60 s stands in the Prep pose until Resume" });
    stopAll.onclick = () => sendStop(api, "all", "stop");
    // Red chip on every page while an operator drives with the referee-rules bypass (/state "bypass", last 5 s)
    const bypass = el("span", { className: "ctl-bypass", title: "Manual commands reach the robot in READY, SET and PLAYING" });
    const bypassName = el("span", { className: "ctl-nm" });
    bypass.hidden = true;
    host.replaceChildren(el("span", { className: "ctl-bar" }, lock, stopAll, bypass));  // an overflow cuts the chip, not STOP ALL

    const setView = (v) => {  // opts.onLost(): this page had control and no longer has it (gave it, or it expired)
        const lost = view.you && !v.you;
        view = v;
        render();
        if (lost) opts.onLost?.(v.holder);
    };
    const act = async (action) => {
        if (action === "release") await opts.beforeRelease?.();
        const r = await post(api, "/control_lock", { action });
        if (r.lock) setView(r.lock);
        if (r.result === "busy") toast("Another operator is already waiting for control. Try again later.", true);
        if (!r.ok) toast(r.error || `HTTP ${r.status}`, true);
        return r;
    };
    const button = (text, onclick, title = "") => el("button", { textContent: text, onclick, title });
    const name = () => {
        const n = el("span", { className: "ctl-name ctl-nm", textContent: operator.name, tabIndex: 0, title: "Your name for the other operators (click to change)" });
        n.onclick = n.onkeydown = (e) => {
            if (e.type === "keydown" && e.key !== "Enter") return;
            const input = el("input", { value: operator.name, maxLength: 40, size: 12 });
            input.setAttribute("aria-label", "Your operator name");
            let closed = false;
            const close = (save) => {  // Enter or click-away saves, Escape cancels; once only (render() blurs the input)
                if (closed) return;
                closed = true;
                const v = input.value.trim();
                if (save && v && v !== operator.name) {
                    operator.name = v;
                    try { localStorage.setItem("oraculum_operator", v); } catch { /* private mode */ }
                    if (view.you || view.waiting) act("take");  // the other operators see the new name at once
                }
                render();
            };
            input.onkeydown = (ev) => { if (ev.key === "Enter") close(true); if (ev.key === "Escape") close(false); };
            input.onblur = () => close(true);
            n.replaceWith(input);
            input.focus();
            input.select();
        };
        return n;
    };
    function render() {
        lock.className = "ctl-lock" + (view.you ? " mine" : "") + (view.request || view.waiting ? " ask" : "");
        const txt = (...kids) => el("span", { className: "ctl-txt" }, ...kids);  // one text run: no gaps inside "(name)"
        const nm = (s) => el("span", { className: "ctl-nm", textContent: s, title: s });  // a long name shortens, the words stay
        if (view.you && view.request) {
            lock.replaceChildren(txt(nm(view.request), " asks for control"), button("Give", () => act("grant")), button("Keep", () => act("deny")));
        } else if (view.you) {
            lock.replaceChildren(txt("Control: you (", name(), ")"), button("Release", () => act("release"), "Let another operator drive"));
        } else if (view.waiting) {
            lock.replaceChildren(txt("Asked ", nm(view.holder), "…"), button("Cancel", () => act("release")));
        } else if (view.holder) {
            lock.replaceChildren(txt("Control: ", nm(view.holder)), button("Ask", () => act("take"), `Ask ${view.holder} to give you control`));
        } else {
            lock.replaceChildren(txt("Control: free", el("span", { className: "ctl-free-nm" }, " (you: ", name(), ")")),
                                 button("Take", () => act("take"), "Only the operator with control can drive robots"));
        }
        lock.title = lock.firstChild.textContent;  // the full text: phones shorten it
    }
    render();
    return {
        update(state) {
            const v = state && state.lock;
            if (v) {
                if (v.denied) { toast(`${v.holder} kept control.`, true); opts.onDenied?.(v.holder); }
                if (JSON.stringify(v) !== JSON.stringify(view)) setView(v);
            }
            // Our own bypass after we released control: the last manual command is up to 5 s old, nobody drives now
            // (another tab of this browser has the same name: while it holds control, the chip stays)
            bypass.hidden = !state?.bypass || (state.bypass === operator.name && !view.you && view.holder !== operator.name);
            if (!bypass.hidden && bypassName.textContent !== state.bypass) {
                bypassName.textContent = state.bypass;
                bypass.replaceChildren(el("span", { className: "ctl-bp-l", textContent: "Bypass" }), el("span", { className: "ctl-bp-s", textContent: "BP" }),
                                       el("span", { className: "ctl-on", textContent: " on" }), ": ", bypassName);
                bypass.title = `Bypass on: ${state.bypass}. Manual commands reach the robot in READY, SET and PLAYING`;
            }
        },
        take: () => act("take"),
        hasControl: () => !!view.you,
        waiting: () => !!view.waiting,
        holder: () => view.holder || "",
        locked(reply) {  // a 423 (lock) or 403 (referee rule) from /control: say it once every 3 s, not 12 times a second
            if (performance.now() - lastLocked < 3000) return;
            lastLocked = performance.now();
            toast(reply.status === "blocked" || !reply.holder ? reply.reason || "Take control in the header first." : `${reply.holder} has control: ask for it in the header.`, true);
        },
    };
}

// Floating, expandable overlays for EVERY page: the simulated-referee (GameController) controls and the recording
// controls. Append once to <body>; the page feeds /state through update(state). GC panel shows only with a simulated
// referee (gamecontroller.sim). Returns { update(state) }.
export function mountOverlays(api, { right = false } = {}) {
    style();
    const wrap = el("div", { className: "ctl-ovl" + (right ? " right" : "") });
    const fab = el("button", { className: "ovl-fab", textContent: "⚑", title: "Record and GameController menus" });
    fab.setAttribute("aria-expanded", "false");
    let openY = 0;  // scrollY when the menus opened
    fab.onclick = () => { openY = scrollY; fab.setAttribute("aria-expanded", String(wrap.classList.toggle("open"))); };
    // Phones: the open menus sit over the page; a tap outside them or a page scroll (more than 40 px: not a layout nudge)
    // closes them, so they cover no cell for long (.ovl-head: a page's own header button for the menus, which toggles them itself)
    const close = () => { if (wrap.classList.contains("open")) { wrap.classList.remove("open"); fab.setAttribute("aria-expanded", "false"); } };
    // The tap that closes the menus does nothing else (it once sent a Resume to the robot under the finger); a STOP
    // button still works at once (.ctl-stop: STOP ALL and every per-robot STOP)
    addEventListener("pointerdown", (e) => {
        if (!wrap.classList.contains("open") || e.target.closest?.(".ctl-ovl, .ovl-head")) return;
        close();
        if (e.target.closest?.(".ctl-stop")) return;
        e.preventDefault();
        e.stopPropagation();
        const swallow = (c) => { c.preventDefault(); c.stopPropagation(); };
        addEventListener("click", swallow, { capture: true, once: true });
        setTimeout(() => removeEventListener("click", swallow, true), 700);  // no click followed (a drag): free the next one
    }, true);
    addEventListener("scroll", () => { if (Math.abs(scrollY - openY) > 40) close(); }, { passive: true });
    const caret = () => el("span", { className: "caret", textContent: "▾" });
    const toggle = (panel, row) => row.addEventListener("click", (e) => {
        if (e.target.tagName === "BUTTON") return;  // a control button inside the panel body does its own thing
        panel.classList.toggle("open");
    });

    // --- GameController (simulated referee) ---
    const gcPanel = el("div", { className: "panel" });
    gcPanel.hidden = true;
    const gcState = el("b", { className: "gcstate", textContent: "—" });
    const gcRow = el("div", { className: "pill-row" }, el("span", {}, "⚑ GC: ", gcState), caret());
    const stateBtns = {};
    const gcBtns = el("div", { className: "btns" });
    for (const [k, lbl] of [["initial", "Initial"], ["ready", "Ready"], ["set", "Set"], ["playing", "Play"], ["finished", "Finish"]]) {
        const b = el("button", { textContent: lbl, onclick: () => post(api, "/gc", { state: k }) });
        gcBtns.append(b);
        stateBtns[k.toUpperCase()] = b;
    }
    const goalBtns = el("div", { className: "btns", style: "margin-top:6px" },
        el("button", { textContent: "Goal A", title: "Goal for the first team", onclick: () => post(api, "/gc", { goal: 0 }) }),
        el("button", { textContent: "Goal B", title: "Goal for the second team", onclick: () => post(api, "/gc", { goal: 1 }) }));
    // Hosted sessions (/state restart): restart the whole session, robots, ball and referee back to the start. Two clicks
    // within 4 s, as the event delete: a wrong tap costs a minute of play.
    let armed = 0;
    const resetBtn = el("button", { textContent: "Reset session", title: "Restart the simulation: robots, ball and referee back to the start (about 1 min)" });
    resetBtn.onclick = async () => {
        if (Date.now() - armed > 4000) { armed = Date.now(); resetBtn.textContent = "Click again: reset all"; setTimeout(() => { resetBtn.textContent = "Reset session"; }, 4000); return; }
        armed = 0; resetBtn.textContent = "Reset session";
        const r = await post(api, "/session_restart", {});
        toast(r.ok ? "Session restarting: robots back to the start in about 1 min" : (r.error || `Reset failed (HTTP ${r.status})`), !r.ok);
    };
    const resetRow = el("div", { className: "btns", style: "margin-top:6px" }, resetBtn);
    resetRow.hidden = true;
    gcPanel.append(gcRow, el("div", { className: "body" }, gcBtns, goalBtns, resetRow));
    toggle(gcPanel, gcRow);

    // --- Recording ---
    let rec = {};
    const recPanel = el("div", { className: "panel" });
    const recPill = el("span", { className: "recpill" }, el("i", { className: "dot2" }), el("span", { className: "rectext", textContent: "Record" }));
    const recRow = el("div", { className: "pill-row" }, recPill, caret());
    const recBtn = el("button", { textContent: "● Record",
        title: "Record all telemetry and GameController packets to oraculum/recordings/" });
    recBtn.onclick = () => post(api, "/record", rec.on ? { on: false, name: rec.name, by: operator.name } : { on: true, by: operator.name });
    const recInfo = el("div", { className: "info" });
    recInfo.hidden = true;
    recPanel.append(recRow, el("div", { className: "body" }, recBtn, recInfo));
    toggle(recPanel, recRow);

    wrap.append(fab, recPanel, gcPanel);  // column-reverse: GC sits above recording, the phone button below both
    document.body.append(wrap, el("div", { className: "ctl-ovl-space" }));
    // --ctl-ovl-h = window bottom to the top of the boxes + 8 px: the pages keep this space free of clickable content
    let ovlH = "";
    const measure = () => {
        const h = `${Math.max(0, Math.ceil(innerHeight - wrap.getBoundingClientRect().top + 8))}px`;
        if (h !== ovlH) document.documentElement.style.setProperty("--ctl-ovl-h", ovlH = h);
    };
    new ResizeObserver(measure).observe(wrap);
    addEventListener("resize", measure);
    return {
        update(state) {
            const gc = (state && state.gamecontroller) || {};
            gcPanel.hidden = !gc.sim;
            resetRow.hidden = !(state && state.restart);
            gcState.textContent = gc.state || "—";
            for (const [k, b] of Object.entries(stateBtns)) b.setAttribute("aria-pressed", String(k === gc.state));
            rec = (state && state.rec) || {};
            recPill.classList.toggle("on", !!rec.on);
            fab.classList.toggle("rec", !!rec.on);
            fab.textContent = rec.on ? "●" : "⚑";
            recPanel.querySelector(".rectext").textContent = rec.on ? "Recording" : "Record";
            recBtn.textContent = rec.on ? "■ Stop recording" : "● Record";
            recInfo.hidden = !rec.on;
            if (rec.on) {
                recInfo.textContent = `${rec.name || ""} · by ${rec.by || "?"} · ${Math.round(rec.secs || 0)}s · ${((rec.bytes || 0) / 1e6).toFixed(1)} MB`;
            }
            measure();  // also follows the MANUAL banner, which lifts the boxes
        },
    };
}

// STOP and Resume for one robot; with {lie: true} also LIE DOWN, sent only after a 2 s press (pointer or Space/Enter).
// Every button names its robot with its team ("STOP T5 R4", "STOP T19 R3·.2"), and STOP is a red outline: only STOP ALL is filled red.
// {named: true}: taller buttons for robot.html, where the buttons sit apart from any card.
export function robotActions(ip, api, { lie = false, label = "", named = false } = {}) {
    style();
    const box = el("span", { className: "ctl-act" + (named ? " named" : "") });
    const name = shortName(label, ip);  // the same text on every page
    const who = () => el("span", { className: "ctl-who", textContent: ` ${name}` });  // its own span: fleet phones put it on line 2
    const stop = el("button", { className: "ctl-stop one", title: `STOP ${label || ip}: stand in the Prep pose until Resume (also ends a DAMP of this robot)` }, "STOP", who());
    stop.onclick = (e) => { e.stopPropagation(); sendStop(api, ip, "stop"); };
    const resume = el("button", { title: `Resume ${label || ip}: the Play combo (needs control)` }, "Resume", who());
    resume.onclick = (e) => { e.stopPropagation(); sendStop(api, ip, "resume"); };
    box.append(stop, resume);
    if (lie) box.append(holdButton("Hold: LIE DOWN", `Hold 2 s: ${label || ip} lies down on its back (controlled) until Resume`, 2000,
                                   () => sendStop(api, ip, "lie"), "", who()));
    return box;
}

// DAMP for one robot: closed by default; typing the robot's word (dampWord in field_model.js) enables a 3 s press-and-hold.
export function dangerDamp(ip, api, label) {
    style();
    label = label || ip;
    const name = dampWord(label, ip);  // the unlock word comes from the full label ("R3.2")
    label = shortName(label, ip);  // the texts use the button spelling ("DAMP T19 R3·.2", as "STOP T19 R3·.2")
    const input = el("input", { placeholder: name, autocomplete: "off", spellcheck: false, title: `Type ${name} to unlock DAMP ${label}` });
    input.setAttribute("aria-label", `Type ${name} to unlock DAMP ${label}`);
    const btn = holdButton(`Hold 3 s: DAMP ${label}`, `DAMP ${label}: the motors go soft and the robot falls. Type ${name} first to unlock this button.`, 3000, () => {
        sendStop(api, ip, "damp", { confirm: ip });
        input.value = ""; btn.disabled = true;
    }, "damp");
    btn.disabled = true;
    input.oninput = () => { btn.disabled = input.value.trim().toUpperCase() !== name.toUpperCase(); };
    return el("details", { className: "ctl-danger" }, el("summary", { textContent: `Danger: DAMP ${label} (the robot falls)` }),
              el("p", { textContent: `DAMP makes the motors soft: ${label} falls and can break. Use LIE DOWN or STOP instead. ` +
                                     `To unlock, type ${name} exactly, then hold the button for 3 s.` }),
              input, btn);
}

function holdButton(text, title, ms, onDone, cls = "", who = "") {
    const fill = el("i", { className: "fill" });
    const [pre, main] = text.includes(": ") ? [text.slice(0, text.indexOf(": ") + 2), text.slice(text.indexOf(": ") + 2)] : ["", text];
    const b = el("button", { className: `ctl-hold ${cls}`, title }, fill, el("span", {}, el("span", { className: "hold-pre", textContent: pre }), main, who));
    let t0 = 0, raf = 0;
    const tick = () => {
        const p = Math.min(1, (performance.now() - t0) / ms);
        fill.style.width = `${p * 100}%`;
        if (p >= 1) { cancel(); onDone(); return; }
        raf = requestAnimationFrame(tick);
    };
    // data-holding: a page must not rebuild this button's row while a hold runs (fleet.html)
    const begin = (e) => { e.preventDefault(); e.stopPropagation(); if (t0 || b.disabled) return; t0 = performance.now(); b.dataset.holding = "1"; raf = requestAnimationFrame(tick); };
    const cancel = () => { t0 = 0; delete b.dataset.holding; cancelAnimationFrame(raf); fill.style.width = "0"; };
    b.addEventListener("pointerdown", begin);
    ["pointerup", "pointerleave", "pointercancel", "blur"].forEach(ev => b.addEventListener(ev, cancel));
    b.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) begin(e); });
    b.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") cancel(); });
    b.addEventListener("click", (e) => e.stopPropagation());
    return b;
}
