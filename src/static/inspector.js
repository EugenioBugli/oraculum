// Robot inspector for index and dashboard: the selected robot's own fields from the last /state (DebugMessageSender:
// battery, Wi-Fi, temperature, CPU, link, state, ball, obstacles, version) plus any debug texts it sends.
// renderInspector(box, linksBox, state, id, ip): `box` gets the values (rebuilt only when they change), `linksBox`
// the links, in their own element: a rebuild between mouse-down and mouse-up would swallow a click.
import { penaltyOf, robotName, roleWord, stateWord } from '/static/field_model.js';

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const STYLE = `
.insp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.insp-card { background: var(--bg-dark, #121316); border: 1px solid var(--border-subtle, #2d3038); border-radius: 8px; padding: 0.55rem;
    display: flex; flex-direction: column; gap: 0.2rem; }
.insp-label { font-size: 0.68rem; color: var(--text-muted, #9095a3); font-weight: 600; }
.insp-val { font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.8rem; white-space: nowrap; font-weight: bold;
    color: var(--text-primary, #eceef2); }
.insp-more { font-size: 0.72rem; font-family: var(--font-mono, ui-monospace, monospace); color: var(--text-secondary, #9fa4b2);
    background: var(--bg-dark, #121316); padding: 0.6rem; border-radius: 8px; border: 1px solid var(--border-subtle, #2d3038); line-height: 1.6; }
.insp-bad { color: var(--accent-red, #ef4444); }
`;
let styled = false;

export function renderInspector(box, linksBox, state, id, ip) {
    if (!styled) {
        document.head.append(Object.assign(document.createElement('style'), { textContent: STYLE }));
        styled = true;
    }
    if (id === null || id === undefined) return;
    state = state || {};
    const a = (state.agents || []).find(x => x.id === id && (x.ip || '127.0.0.1') === ip);
    let html;
    if (!a) {
        html = `<div style="font-size: 0.8rem; color: var(--text-secondary, #9fa4b2); padding: 0.4rem 0;">R${esc(id)} (${esc(ip)}) sends no data now.</div>`;
    } else {
        const s = a.sys || {}, l = (state.fleet && state.fleet.link && state.fleet.link[a.ip]) || {}, head = state.fleet && state.fleet.head;
        const n = (v, d, u) => typeof v === 'number' && v >= 0 ? v.toFixed(d) + u : '—';
        const hash = String(s.version || '').split(/[+ ]/)[0];
        const ver = !s.version ? '—' : s.version === 'dev' ? 'dev build' : (head && hash !== head ? `✗ ${esc(s.version)} (checkout ${esc(head)})` : `✓ ${esc(s.version)}`);
        const card = (label, val) => `<div class="insp-card"><span class="insp-label">${label}</span><span class="insp-val">${val}</span></div>`;
        const latch = ({ damp: ' · <b class="insp-bad">DAMPED</b>', lie: ' · <b class="insp-bad">LYING</b>', stop: ' · <b class="insp-bad">STOPPED</b>' })[a.latch] || '';
        const texts = (state.texts || []).filter(t => t.agent_id === a.id);
        html = `
        <div style="display: flex; flex-direction: column; gap: 0.7rem;">
            <div style="font-size: 0.85rem; font-weight: bold; color: var(--accent-cyan, #22d3ee); display: flex; justify-content: space-between;
                        border-bottom: 1px solid var(--border-subtle, #2d3038); padding-bottom: 0.45rem;">
                <span>${esc(robotName(a))}</span>
                <span style="font-family: var(--font-mono, monospace); font-size: 0.75rem; color: var(--text-secondary, #9fa4b2);">${esc(a.ip)}</span>
            </div>
            <div class="insp-grid">
                ${card('BATTERY', a.battery >= 0 ? (a.battery < 20 ? '⚠ ' : '') + a.battery.toFixed(0) + '%' : 'n/a')}
                ${card('WI-FI ↑ / ↓ KBIT/S', `${n(s.tx, 0, '')} / ${n(s.rx, 0, '')}`)}
                ${card('TEMP · CPU', `${n(s.temp, 0, '°C')} · ${n(s.cpu, 0, '%')}`)}
                ${card('LINK', `${n(l.hz, 0, ' Hz')} · ${n(l.age, 1, ' s')}`)}
            </div>
            <div class="insp-more">
                <div>State: ${esc(stateWord(a.state))}${a.fallen ? ' · <b class="insp-bad">⚠ FALLEN</b>' : ''}${latch} · Role: ${esc(roleWord(a.role))}</div>
                ${penaltyOf(a, state.gamecontroller) ? `<div><b class="insp-bad">⛔ ${esc(penaltyOf(a, state.gamecontroller))}</b></div>` : ''}
                <div>Ball: ${a.ball ? `${a.ball.x.toFixed(2)}, ${a.ball.y.toFixed(2)} m` : 'not seen'} · Obstacles: ${(a.obstacles || []).length}</div>
                <div>Version: ${ver}</div>
                <div>Load: ${n(s.load, 1, '')}${s.rec ? ' · ● recording' : ''}</div>
                ${texts.map(t => `<div>${esc(t.path)}: ${esc(t.text)}</div>`).join('')}
            </div>
        </div>`;
    }
    if (html !== box.dataset.html) {
        box.innerHTML = html;
        box.dataset.html = html;
    }
    const key = encodeURIComponent(`${ip}|${id}`);
    const links = `<div style="display: flex; gap: 0.8rem; font-size: 0.78rem;"><a href="/robot.html?robot=${key}" style="color: #93c5fd;">Robot ›</a><a href="/fleet.html" style="color: #93c5fd;">Fleet &amp; events ›</a></div>`;
    if (linksBox && linksBox.dataset.html !== links) {
        linksBox.innerHTML = links;
        linksBox.dataset.html = links;
    }
}
