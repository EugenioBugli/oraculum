// STOP and engineer mode for every page (index, dashboard, fleet, robot).
// - mountControlBar(el, api): STOP ALL and the control lock (src/control_lock.py) in the page header.
// - robotActions(ip, api, {lie}): STOP, Resume and (only where asked) a 2 s press-and-hold LIE DOWN for one robot.
// - dangerDamp(ip, api, label): DAMP drops the robot and can break it: a closed "Danger" section, the robot's name
//   typed to unlock, then a 3 s press-and-hold. The gateway also refuses DAMP for "all" and without confirm.
// - stateUrl(api) / withOperator(body): every /state poll and /control body carries this tab's client id, so the
//   gateway knows who holds the lock and that the holder's page is still open.
// STOP, LIE DOWN and DAMP need no lock and pass the GameController rule (POST /stop). The gateway answers "sent": the robot
// does not confirm yet, so no button claims the robot stopped.

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
@media (max-width: 700px) { .hold-pre { display: none; } }  /* "Hold: LIE DOWN" -> "LIE DOWN" on phones (still a 2 s hold) */
@media (max-width: 900px) { .ctl-nm { max-width: 9ch; } .ctl-bar { flex-wrap: nowrap; } }
@media (pointer: coarse) { .ctl-bar button, .ctl-act button { min-height: 40px; } }  /* touch targets */
.ctl-lock.mine { color: #10b981; border-color: #10b981; }
.ctl-lock.ask { color: #f59e0b; border-color: #f59e0b; }
.ctl-bar button, .ctl-act button { font: 700 12px var(--font, system-ui, sans-serif); border-radius: 6px; padding: 4px 9px;
    border: 1px solid var(--border-strong, #3b3f4a); background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); cursor: pointer; }
.ctl-bar button:focus-visible, .ctl-act button:focus-visible { outline: 2px solid #f59e0b; outline-offset: 2px; }
.ctl-name { cursor: pointer; text-decoration: underline dotted; }
button.ctl-stop { background: #dc2626; border-color: #dc2626; color: #fff; letter-spacing: .04em; }
button.ctl-stopall { padding: 5px 14px; font-size: 13px; white-space: nowrap; }
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
    background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); width: 7em; margin-right: 6px; }
.ctl-toast { position: fixed; bottom: 84px; left: 0; right: 0; margin: 0 auto; width: fit-content; z-index: 9999; max-width: min(92vw, 560px);
    padding: 8px 14px; border-radius: 8px; font: 600 13px var(--font, system-ui, sans-serif); color: #fff; background: #065f46;
    box-shadow: 0 6px 24px rgba(0,0,0,.4); }
.ctl-toast.err { background: #991b1b; }
body > .ctl-toast { visibility: visible !important; }  /* also over a "turn your device" overlay that hides the page */
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
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, error ? 8000 : 4000);
}

async function post(api, path, body) {
    try {
        const r = await fetch(`${base(api)}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                body: JSON.stringify({ ...body, client: operator.client, name: operator.name }) });
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
export function mountControlBar(host, api, opts = {}) {
    style();
    let view = { holder: null }, lastLocked = 0;
    const lock = el("span", { className: "ctl-lock" });
    lock.setAttribute("aria-live", "polite");
    const stopAll = el("button", { className: "ctl-stop ctl-stopall", textContent: "STOP ALL",
                                   title: "Every robot heard in the last 60 s stands in the Prep pose until Resume" });
    stopAll.onclick = () => sendStop(api, "all", "stop");
    host.replaceChildren(el("span", { className: "ctl-bar" }, lock, stopAll));

    const setView = (v) => {  // opts.onLost(): this page had control and no longer has it (gave it, or it expired)
        const lost = view.you && !v.you;
        view = v;
        render();
        if (lost) opts.onLost?.(v.holder);
    };
    const act = async (action) => {
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
            lock.replaceChildren(txt("Control: free · ", name()), button("Take", () => act("take"), "Only the operator with control can drive robots"));
        }
    }
    render();
    return {
        update(state) {
            const v = state && state.lock;
            if (!v) return;
            if (v.denied) { toast(`${v.holder} kept control.`, true); opts.onDenied?.(v.holder); }
            if (JSON.stringify(v) !== JSON.stringify(view)) setView(v);
        },
        take: () => act("take"),
        hasControl: () => !!view.you,
        waiting: () => !!view.waiting,
        holder: () => view.holder || "",
        locked(reply) {  // a 423 (lock) or 403 (referee rule) from /control: say it once every 3 s, not 12 times a second
            if (performance.now() - lastLocked < 3000) return;
            lastLocked = performance.now();
            toast(reply.status === "blocked" ? reply.reason : `${reply.holder || "Another operator"} has control: ask for it in the header.`, true);
        },
    };
}

// STOP and Resume for one robot; with {lie: true} also LIE DOWN, sent only after a 2 s press (pointer or Space/Enter).
export function robotActions(ip, api, { lie = false, label = "" } = {}) {
    style();
    const box = el("span", { className: "ctl-act" });
    const stop = el("button", { className: "ctl-stop", textContent: "STOP", title: `STOP ${label || ip}: stand in the Prep pose until Resume (also ends a DAMP of this robot)` });
    stop.onclick = (e) => { e.stopPropagation(); sendStop(api, ip, "stop"); };
    const resume = el("button", { textContent: "Resume", title: `Resume ${label || ip}: the Play combo (needs control)` });
    resume.onclick = (e) => { e.stopPropagation(); sendStop(api, ip, "resume"); };
    box.append(stop, resume);
    if (lie) box.append(holdButton("Hold: LIE DOWN", `Hold 2 s: ${label || ip} lies down on its back (controlled) until Resume`, 2000,
                                   () => sendStop(api, ip, "lie")));
    return box;
}

// DAMP for one robot: closed by default; typing the robot's name enables a 3 s press-and-hold.
export function dangerDamp(ip, api, label) {
    style();
    const name = (label || ip).split(" ").pop();  // "T19 R3" -> "R3"
    const input = el("input", { placeholder: name, autocomplete: "off", spellcheck: false });
    input.setAttribute("aria-label", `Type ${name} to unlock DAMP`);
    const btn = holdButton("Hold 3 s: DAMP", `DAMP ${label || ip}: the motors go soft and the robot falls`, 3000, () => {
        sendStop(api, ip, "damp", { confirm: ip });
        input.value = ""; btn.disabled = true;
    }, "damp");
    btn.disabled = true;
    input.oninput = () => { btn.disabled = input.value.trim().toUpperCase() !== name.toUpperCase(); };
    return el("details", { className: "ctl-danger" }, el("summary", { textContent: "Danger: DAMP (the robot falls)" }),
              el("p", { textContent: `DAMP makes the motors soft: ${label || ip} falls and can break. Use LIE DOWN or STOP instead. ` +
                                     `To unlock, type ${name}, then hold the button for 3 s.` }),
              input, btn);
}

function holdButton(text, title, ms, onDone, cls = "") {
    const fill = el("i", { className: "fill" });
    const [pre, main] = text.includes(": ") ? [text.slice(0, text.indexOf(": ") + 2), text.slice(text.indexOf(": ") + 2)] : ["", text];
    const b = el("button", { className: `ctl-hold ${cls}`, title }, fill, el("span", {}, el("span", { className: "hold-pre", textContent: pre }), main));
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
