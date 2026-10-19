// Field model and robot beliefs, shared by index.html, dashboard.html and robot.html.
//
// FIELD: the field of the gateway's config.yaml (fields/*.yaml, metres), from GET /field; the defaults are
// fieldAdultSize.yaml (circus fieldLarge, 14 x 9 m). loadField() updates FIELD in place.
// beliefDrawings(): each robot's own ball estimate and the obstacles it sees, as debug drawings in the field
// frame (paths "beliefs/ball" and "beliefs/obstacles"), so every engine draws them and the drawing filter hides them.

export const FIELD = {
    width: 14, height: 9, center_radius: 1.5, goal_area_width: 1, goal_area_height: 4, penalty_area_width: 3,
    penalty_area_height: 6.5, penalty_mark_distance: 2.1, goal_width: 2.6, goal_height: 1.8, goal_depth: 0.6,
};

export async function loadField(api, timeoutMs = 1500) {
    try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), timeoutMs);
        const f = await (await fetch(`${api}/field`, { signal: ctl.signal })).json();
        clearTimeout(timer);
        if (f && f.width > 0 && f.height > 0) Object.assign(FIELD, f);
    } catch (e) {
        console.warn('[field] GET /field failed, using the 14 x 9 m defaults', e);
    }
    return FIELD;
}

// Field lines as polylines [[x, y], ...]: border, halfway line, centre circle, goal and penalty areas, marks.
export function fieldLines(f = FIELD) {
    const L = f.width / 2, W = f.height / 2, out = [];
    const rect = (x0, x1, h) => [[x0, -h], [x1, -h], [x1, h], [x0, h], [x0, -h]];
    out.push(rect(-L, L, W), [[0, -W], [0, W]]);
    out.push(Array.from({ length: 65 }, (_, k) => [f.center_radius * Math.cos(k * Math.PI / 32), f.center_radius * Math.sin(k * Math.PI / 32)]));
    for (const s of [-1, 1]) {
        out.push(rect(s * L, s * (L - f.goal_area_width), f.goal_area_height / 2), rect(s * L, s * (L - f.penalty_area_width), f.penalty_area_height / 2));
        const px = s * (L - f.penalty_mark_distance);
        out.push([[px - 0.05, 0], [px + 0.05, 0]], [[px, -0.05], [px, 0.05]]);
    }
    return out;
}

// The 10 team colour names of the GameController (the robots send them in lowercase), as display colours.
const TEAM_RGB = {
    blue: [59, 130, 246], red: [229, 72, 77], yellow: [250, 204, 21], black: [0, 0, 0], white: [255, 255, 255],
    green: [34, 197, 94], orange: [249, 115, 22], purple: [168, 85, 247], brown: [146, 64, 14], gray: [128, 128, 128],
};

// [r, g, b] of a team colour name or "#rrggbb", or null.
export function rawRgb(color) {
    const c = String(color || '').toLowerCase();
    if (TEAM_RGB[c]) return TEAM_RGB[c];
    const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/.exec(c);
    return m ? m.slice(1).map(h => parseInt(h, 16)) : null;
}

// Display colour of a robot's team on the dark pages: unknown -> grey; dark colours lifted by adding, not
// multiplying, so black becomes grey (140, 140, 140) and #822433 stays about (140, 46, 61).
// One name for a robot on every page: team number and player number, "T19 R3" (both teams have players 1-5).
// The 3D and 2D badges stay "R3" in the team colour.
export const robotName = a => `T${a?.team || '?'} R${a?.id ?? '?'}`;

// Words for the one-letter role and state of the telemetry (the robots send full role names; the fake sender letters).
const ROLE_WORDS = { G: 'Goalkeeper', D: 'Defender', M: 'Midfielder', A: 'Attacker' };
const STATE_WORDS = { I: 'Idle', R: 'Running', S: 'Stopped by GC', P: 'Penalised', X: 'Error' };
export const roleWord = r => ROLE_WORDS[r] || r || '—';
export const stateWord = s => STATE_WORDS[s] || s || '—';
export const roleState = a => `${roleWord(a?.role)} · ${stateWord(a?.state)}`;

// Version mark of a robot against the robot-code checkout of the gateway (fleet.head): "✓", "✗" or "" (unknown / dev).
export function versionMark(agent, head) {
    const v = agent?.sys?.version;
    if (!v || v === 'dev' || !head) return '';
    return v.split(/[+ ]/)[0] === head ? '✓' : '✗';
}

// "7/7 online · 2 fallen · 0 penalised · 1 low battery · 1 wrong version" for the main page. `seen` (Map: robot key ->
// {agent, t}) is kept by the page: a robot silent for less than 60 s counts as offline, as in the fleet table.
export function teamSummary(state, seen, now = Date.now()) {
    const agents = state?.agents || [], key = a => `${a.ip}|${a.id}`;
    for (const a of agents) seen.set(key(a), { agent: a, t: now });
    for (const [k, v] of seen) if (now - v.t > 60000) seen.delete(k);
    const gc = state?.gamecontroller, head = state?.fleet?.head;
    const n = f => agents.filter(f).length;
    return [`${agents.length}/${seen.size} online`, `${n(a => a.fallen)} fallen`, `${n(a => penaltyOf(a, gc) || a.state === 'P')} penalised`,
            `${n(a => a.battery >= 0 && a.battery < 20)} low battery`, `${n(a => versionMark(a, head) === '✗')} wrong version`].join(' · ');
}

// GameController pill for every page. No packet for 2 s → "No GameController" and no fake "00:00 0 - 0";
// otherwise the state, the score with team numbers, the half, the clock and a running set play.
const mmss = s => `${s < 0 ? '-' : ''}${Math.floor(Math.abs(s) / 60)}:${String(Math.abs(s) % 60).padStart(2, '0')}`;
export function gcSummary(gc) {
    gc = gc || {};
    if (!gc.state) return { online: false, state: 'No GameController', detail: '', score: '', title: 'No GameController packet on UDP 3838 in the last 2 s' };
    const [t0, t1] = gc.teams || [], [s0, s1] = gc.score || [0, 0];
    const detail = [gc.first_half === false ? '2nd half' : '1st half', mmss(gc.secsRemaining || 0)];
    if (gc.set_play_name) detail.push(`${gc.set_play_name}${gc.secondary_time ? ` ${gc.secondary_time} s` : ''}`);
    if (gc.phase && gc.phase !== 'NORMAL') detail.push(gc.phase.replaceAll('_', ' '));
    return { online: true, state: gc.state, detail: detail.join(' · '), score: `T${t0 ?? '?'} ${s0} – ${s1} T${t1 ?? '?'}`,
             title: `GameController: last packet ${gc.age ?? '?'} s ago from ${gc.source || '?'}` };
}
// A robot's GameController penalty, e.g. "Leaving the field · 23 s", or "".
export function penaltyOf(agent, gc) {
    const p = gc?.penalties?.[String(agent?.team)]?.[String(agent?.id)];
    return p ? `${p[0]} · ${p[1]} s` : '';
}

export function teamRgb(agent) {
    const rgb = rawRgb(agent.color);
    if (!rgb) return [159, 164, 178];
    const lift = Math.max(0, 140 - Math.max(...rgb));
    return rgb.map(v => Math.min(255, v + lift));
}

const ok = (p) => p && Number.isFinite(p.x) && Number.isFinite(p.y);

export function beliefDrawings(agents) {
    const out = [];
    for (const a of agents || []) {
        if (!ok(a)) continue;
        const color = teamRgb(a);
        if (ok(a.ball)) {
            out.push({ type: 'line', path: 'beliefs/ball', coords: [a.x, a.y, a.ball.x, a.ball.y], color, size: 1, dash: true, agent_id: a.id },
                     { type: 'point', path: 'beliefs/ball', coords: [a.ball.x, a.ball.y], color, size: 0.07, agent_id: a.id });
        }
        for (const o of a.obstacles || []) {
            if (ok(o)) out.push({ type: 'circle', path: 'beliefs/obstacles', coords: [o.x, o.y], color, size: 0.25, dash: true, agent_id: a.id });
        }
    }
    return out;
}

// Debug drawings on a 2D canvas (moved from index.html). map(x, y, frame) -> {x, y} canvas px;
// size(s, frame) -> canvas px; frame "field" (metres) or "viewport" (0..1). hidden: Set of paths not drawn.
export function drawDrawings2D(ctx, drawings, map, size, hidden, px = 1) {  // px: canvas px per CSS px
    for (const dr of drawings || []) {
        if (dr.path && hidden && hidden.has(dr.path)) continue;
        const coords = dr.coords;
        if (!coords || coords.length === 0) continue;
        const color = dr.color ? `rgb(${dr.color[0]}, ${dr.color[1]}, ${dr.color[2]})` : '#ffffff';
        const frame = dr.frame || 'field';
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        // A line's size is its width in px; for the other types size is a radius in metres, so they get a fixed width.
        ctx.lineWidth = (dr.type === 'line' ? Math.max(1.5, dr.size || 2) : 1.5) * px;
        ctx.setLineDash(dr.dash ? [5 * px, 4 * px] : []);
        if (dr.type === 'point') {
            const pt = map(coords[0], coords[1], frame);
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, Math.max(2, size(dr.size || 0.05, frame)), 0, 2 * Math.PI);
            ctx.fill();
        } else if (dr.type === 'circle') {
            const pt = map(coords[0], coords[1], frame);
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, size(dr.size || 0.1, frame), 0, 2 * Math.PI);
            ctx.stroke();
        } else if (dr.type === 'line' && coords.length >= 4) {
            const p1 = map(coords[0], coords[1], frame), p2 = map(coords[2], coords[3], frame);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        } else if (dr.type === 'box' && coords.length >= 4) {
            const [cx, cy, w, h] = coords, tl = map(cx - w / 2, cy + h / 2, frame);
            ctx.strokeRect(tl.x, tl.y, size(w, frame), size(h, frame));
        } else if (dr.type === 'arc' && coords.length >= 2) {
            const pt = map(coords[0], coords[1], frame);
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, size(coords[2] || dr.size || 0.2, frame), (coords[3] || 0) * Math.PI / 180, (coords[4] || 360) * Math.PI / 180);
            ctx.stroke();
        }
    }
    ctx.setLineDash([]);
}

// One robot in a 2D arena: disc in its colour, heading tick from the rim, number readable on any fill.
// px = canvas pixels per CSS pixel, so the robot and its number keep their screen size. ring = selection colour or null.
export function drawRobot2D(ctx, agent, x, y, px, ring) {
    const r = 12 * px, a = Number.isFinite(agent.angle) ? agent.angle : 0;
    if (ring) {
        ctx.strokeStyle = ring;
        ctx.lineWidth = 4 * px;
        ctx.beginPath();
        ctx.arc(x, y, r + 6 * px, 0, 2 * Math.PI);
        ctx.stroke();
    }
    ctx.fillStyle = agent.color || '#822433';
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2 * px;
    ctx.stroke();
    ctx.beginPath();  // heading: from the rim outwards, so it never crosses the number
    ctx.moveTo(x + r * Math.cos(a), y - r * Math.sin(a));
    ctx.lineTo(x + (r + 8 * px) * Math.cos(a), y - (r + 8 * px) * Math.sin(a));
    ctx.stroke();
    const c = rawRgb(agent.color);
    const lum = c ? (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 : 0;
    ctx.fillStyle = lum > 0.6 ? '#111' : '#fff';
    ctx.font = `bold ${Math.round(12 * px)}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(agent.id, x, y + px);
    ctx.textBaseline = 'alphabetic';
}
