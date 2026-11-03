// Command panel of the selected robot, shared by index.html and dashboard.html. Top: the robot's name, a live 3D
// miniature and its role, state and latch. Middle: the page's own joystick (its markup and code stay in the page).
// Bottom: STOP, Resume, Get up, LIE DOWN (2 s hold), Go to a position (GET /positions, POST /goto) and Drop =
// DAMP (dangerDamp: typed word + 3 s hold). The joystick and the commands show only once a robot is selected.
// A match-mode robot (sys.link "telemetry") and a read-only robot (no oraculum telemetry: another branch or team, seen by
// team message or GameController return) take no command: the buttons are disabled and their tooltip says why.
// The commands are built once per robot, so a running 2 s hold survives the 10 Hz polls.
// Miniature: one small Three.js renderer for the selected robot, posed from its telemetry joints by the MuJoCo models of
// mujoco_robots.js (one load per page, shared with the wasm engine); drawn once per /state, only while visible.
// Without WebGL2 or the model files it is the 2D disc of the field view.
import { miniature } from "./robot_viewer.js";
import { dangerDamp, robotActions, sendGoto } from "./control_bar.js";
import { READONLY_TIP, latchWord, readOnly, roleState, robotName, shortName, teamRgb } from "./field_model.js";

const STYLE = `
.rp-off, .rp-cmds[hidden] { display: none !important; }
.rp-empty { color: var(--text-muted, #6b7080); font-size: 0.75rem; padding: 0.4rem 0; }
.rp-head { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
.rp-mini { width: 96px; height: 120px; flex-shrink: 0; border-radius: 8px; background: radial-gradient(circle at 50% 30%, #2f3646, #14171d); }
.rp-info { min-width: 0; display: flex; flex-direction: column; gap: 3px; font: 600 0.72rem var(--font-mono, ui-monospace, monospace); color: var(--text-secondary, #9fa4b2); }
.rp-name { font: 800 1rem var(--font, system-ui, sans-serif); color: var(--text-primary, #eceef2); border-left: 4px solid; padding-left: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rp-warn { color: #f59e0b; } .rp-latch { color: #f87171; }
.rp-cmds { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; }
.rp-cmds .ctl-act button:disabled { opacity: .45; cursor: not-allowed; }
.rp-goto { align-items: center; }
.rp-secondary { border-top:1px solid var(--border-subtle,#343d52); padding-top:7px; }
.rp-secondary summary { cursor:pointer; font-size:12px; color:var(--text-secondary,#bcc5d6); padding:4px 0; }
.rp-secondary[open] summary { margin-bottom:7px; }
.rp-goto select { flex: 1 1 9em; min-width: 0; min-height: 30px; font: 600 12px var(--font, system-ui, sans-serif); border-radius: 6px;
    border: 1px solid var(--border-strong, #3b3f4a); background: var(--bg-input, #2b2e37); color: var(--text, #eceef2); }
@media (pointer: coarse) { .rp-goto select { min-height: 40px; } }
`;
const el = (tag, props = {}, ...kids) => { const e = Object.assign(document.createElement(tag), props); e.append(...kids); return e; };
const MATCH = "Match mode (oraculum: match): this robot sends telemetry only and takes no command";

// root: the panel; inside it .rp-empty (the hint before a selection), .rp-gated (hidden until a robot is selected),
// .rp-head and .rp-cmds (filled here). extra(): fields for every command body (the page's testingOverride).
// Returns {update(state, id, ip)}: the page calls it after each /state and on a new selection.
export function mountRobotPanel(root, api, { extra = () => ({}) } = {}) {
    document.head.append(el("style", { textContent: STYLE }));
    const base = () => typeof api === "function" ? api() : api;
    const mini = miniature();
    const name = el("div", { className: "rp-name" }), line1 = el("div"), line2 = el("div");
    root.querySelector(".rp-head").replaceChildren(mini.host, el("div", { className: "rp-info" }, name, line1, line2));
    const cmdsHost = root.querySelector(".rp-cmds");
    let key = "", cmds = null, lastSel = null;
    // GET /positions?robot=<ip>: the positions in the shared field frame for that robot's team (mirrored for blue), so the
    // panel can name a go-to target it sees in /state. Per address: undefined = not asked yet, null = loading.
    const positionsOf = new Map(), whyNone = new Map();  // whyNone: the gateway's error, e.g. one IP with robots of two teams
    async function loadPositions(ip) {
        positionsOf.set(ip, null);  // loading
        try {
            const r = await fetch(`${base()}/positions?robot=${encodeURIComponent(ip)}`);
            const j = await r.json();
            positionsOf.set(ip, j.positions || []);
            if (j.error) whyNone.set(ip, `No positions: ${j.error}`);
        } catch { positionsOf.set(ip, []); }  // an old gateway answers index.html here: no positions
        if (lastSel?.[2] === ip) { cmds?.fill(); panel.update(...lastSel); }
    }

    function build(agent, ip, label) {
        const who = () => el("span", { textContent: ` ${shortName(label, ip)}` });
        const acts = robotActions(ip, api, { lie: true, getup: true, label, extra, sit: false });  // SIT is unavailable in the installed SDK
        const select = el("select", { title: "Go-to target: this robot's own positions first" });
        select.setAttribute("aria-label", `Go-to target of ${shortName(label, ip)}`);
        const go = el("button", { title: `Go ${label}: walk to the chosen position (field frame)` }, "Go", who());
        const cancel = el("button", { title: `Cancel the go-to of ${label}: the robot stops walking there` }, "Cancel", who());
        go.onclick = () => {  // by name: the gateway resolves it in the robot's own team frame
            const p = (positionsOf.get(ip) || []).find(q => q.id === select.value);
            if (p) sendGoto(api, ip, { pos: p.id, label: p.label }, extra());
        };
        cancel.onclick = () => sendGoto(api, ip, { cancel: true }, extra());
        const damp = dangerDamp(ip, api, label);
        damp.querySelector("summary").textContent = `Drop: DAMP ${shortName(label, ip)} (the robot falls)`;
        const fill = () => {  // this robot's player number first ("Ready R3"), then the others (side line, …)
            const positions = positionsOf.get(ip);
            if (!positions) return;
            const mine = positions.filter(p => p.player === agent.id), rest = positions.filter(p => p.player !== agent.id);
            select.replaceChildren(...(!positions.length ? [el("option", { textContent: whyNone.get(ip) || "No positions from the gateway", value: "" })]
                : [[`R${agent.id}`, mine], ["Other positions", rest]].filter(([, l]) => l.length)
                    .map(([g, l]) => el("optgroup", { label: g }, ...l.map(p => el("option", { value: p.id, textContent: p.label }))))));
        };
        select.append(el("option", { textContent: "Loading positions…", value: "" }));
        fill();
        const posture = el("details", { className: "rp-secondary" }, el("summary", { textContent: "Posture & recovery" }));
        const postureButtons = el("div", { className: "ctl-act" }, ...acts.querySelectorAll(".ctl-more, .ctl-hold"));
        posture.append(postureButtons);
        const navigation = el("details", { className: "rp-secondary" }, el("summary", { textContent: "Go to position" }),
            el("div", { className: "ctl-act rp-goto" }, select, go, cancel));
        cmdsHost.replaceChildren(el("div", { className: "rp-cmds" }, acts, posture, navigation, damp));
        const gated = [...postureButtons.querySelectorAll(".ctl-more, .ctl-hold"), go, cancel];
        gated.forEach(b => { b.dataset.title = b.title; });
        return { gated, go, fill, dampInput: damp.querySelector("input"), dampBtn: damp.querySelector("button") };
    }

    const panel = {
        update(state, id, ip) {
            const selected = id !== null && id !== undefined;
            root.querySelectorAll(".rp-gated").forEach(e => e.classList.toggle("rp-off", !selected));
            root.querySelector(".rp-empty")?.classList.toggle("rp-off", selected);
            if (!selected) { lastSel = null; mini.clear(); return; }
            lastSel = [state, id, ip];
            if (!positionsOf.has(ip)) loadPositions(ip);
            const positions = positionsOf.get(ip) || [];
            const agents = state?.agents || [];
            const agent = agents.find(a => a.id === id && (a.ip || "127.0.0.1") === ip);
            const label = agent ? robotName(agent, agents) : `R${id}`;
            const k = `${ip}|${id}|${label}|${agent?.robot}|${readOnly(agent)}|${agent?.sys?.link}|${!!state?.match}`;  // rebuild when command capability changes
            if (k !== key) { key = k; cmds = build(agent || { id }, ip, label); }
            name.textContent = shortName(label, ip);
            name.title = `${label} · ${ip}${agent?.robot ? ` · ${agent.robot.toUpperCase()}` : ""}`;
            name.style.borderColor = agent ? `rgb(${teamRgb(agent)})` : "transparent";
            const ro = readOnly(agent), match = ro || !!state?.match || agent?.sys?.link === "telemetry", tip = ro ? READONLY_TIP : MATCH;
            line1.textContent = agent ? roleState(agent) : "not in /state now";
            const goto = agent?.goto, p = goto && positions.find(q => Math.hypot(q.x - goto.x, q.y - goto.y) < 0.05);
            line2.replaceChildren(...[
                agent?.latch && el("span", { className: "rp-latch", textContent: latchWord(agent.latch) }),
                goto && el("span", { textContent: `→ ${p ? p.label : `(${goto.x.toFixed(1)}, ${goto.y.toFixed(1)})`}` }),
                agent?.fallen && el("span", { className: "rp-latch", textContent: "fallen" }),
                match && el("span", { className: "rp-warn", textContent: agent?.simulated ? "local joystick preview" : ro ? "read-only" : "match mode", title: agent?.simulated ? "Only MANUAL moves this browser-local ghost" : tip }),
            ].filter(Boolean).flatMap((e, i) => i ? [" · ", e] : [e]));
            for (const b of cmds.gated) {
                const noPos = b === cmds.go && !positions.length;
                b.disabled = match || noPos;
                b.title = match ? tip : noPos ? whyNone.get(ip) || "The gateway sends no positions (GET /positions)" : b.dataset.title;
            }
            cmds.dampInput.disabled = match;
            cmds.dampInput.title = match ? tip : "";
            if (match) cmds.dampBtn.disabled = true;
            cmdsHost.hidden = !!(agent?.simulated || match);
            if (match) cmdsHost.querySelectorAll("button, input, select").forEach(b => { b.disabled = true; b.title = tip; });  // STOP, Resume too
            if (agent) mini.show(agent); else mini.clear();
        },
    };
    return panel;
}
