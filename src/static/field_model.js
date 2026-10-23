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
// agents (optional, the robots on screen): when another robot has the same team and number on another address, the
// last part of the IP is added, "T19 R3 ·.2" (the whole IP if that part is the same too), so no two robots read alike.
// Twins are looked up among the robots seen in the last 60 s (the fleet table's offline window), not only the robots
// in `agents`: a twin that went stale or silent keeps both suffixes, so the live robot never takes the bare name.
const knownRobots = new Map();  // "ip|team|id" -> {a, t}
export function robotName(a, agents) {
    const name = `T${a?.team || '?'} R${a?.id ?? '?'}`;
    if (!Array.isArray(agents)) return name;  // also .map(robotName): the 2nd argument is then an index
    const now = Date.now();
    for (const b of [a, ...agents]) if (b) knownRobots.set(`${b.ip || '127.0.0.1'}|${b.team}|${b.id}`, { a: b, t: now });
    for (const [k, v] of knownRobots) if (now - v.t > 60000) knownRobots.delete(k);
    const ip = a?.ip || '127.0.0.1', twins = [...knownRobots.values()].map(v => v.a)
        .filter(b => b.team === a?.team && b.id === a?.id && (b.ip || '127.0.0.1') !== ip);
    if (!twins.length) return name;
    const last = x => x.split('.').pop();
    return `${name} ·${twins.some(b => last(b.ip || '127.0.0.1') === last(ip)) ? ip : '.' + last(ip)}`;
}
// Robots in a /state and how many of them have a stale link: the header says "all robot links stale" or "N link stale".
export const linkCounts = state => ({ n: (state?.agents || []).length, stale: (state?.agents || []).filter(a => linkStale(state, a)).length });
// The part robotName adds for a twin ("·.2" -> ".2"), or "": the 2D discs show it under the number.
export const robotTag = (a, agents) => robotName(a, agents).split(' ·')[1] || '';
// Parts of a robotName label: "T19 R3 ·.2" -> number "R3", twin tag ".2" ("" when the robot has no twin).
const labelParts = label => ({ num: String(label || '').match(/\bR\d+\b/)?.[0] || '', tag: String(label || '').split(' ·')[1] || '' });
// "T19 R3", or "T19 R3·.2" for a twin: the name in every button and in the MANUAL banner ("STOP T5 R4"), so two teams'
// robot 4 never share a button text.
export const shortName = (label, ip = '') => String(label || '').replace(' ·', '·') || ip;
// The word that unlocks DAMP: "R3", or "R3.2" for the twin "T19 R3 ·.2", so each twin asks for its own word.
export const dampWord = (label, ip = '') => { const { num, tag } = labelParts(label); return num ? num + (tag ? (tag.startsWith('.') ? tag : `.${tag}`) : '') : ip; };
// The gateway heard nothing from this robot's address for 1 s or more: its data on screen is old (cards say "LINK N s old").
export const linkStale = (state, a) => (state?.fleet?.link?.[a?.ip]?.age ?? 0) >= 1;

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

// "7/7 live · 2 fallen · 0 penalised · 1 low battery · 1 wrong version" for the main page. `seen` (Map: robot key ->
// {agent, t}) is kept by the page: a robot silent for less than 60 s counts as offline, as in the fleet table.
export function teamSummary(state, seen, now = Date.now()) {
    const agents = state?.agents || [], key = a => `${a.ip}|${a.id}`;
    for (const a of agents) seen.set(key(a), { agent: a, t: now });
    for (const [k, v] of seen) if (now - v.t > 60000) seen.delete(k);
    const gc = state?.gamecontroller, head = state?.fleet?.head;
    const n = f => agents.filter(f).length;
    const stale = a => linkStale(state, a);  // a robot with old data is not counted as live
    return [`${n(a => !stale(a))}/${seen.size} live`, `${n(a => a.fallen)} fallen`, `${n(a => penaltyOf(a, gc) || a.state === 'P')} penalised`,
            `${n(a => a.battery >= 0 && a.battery < 20)} low battery`, `${n(a => versionMark(a, head) === '✗')} wrong version`]
        .concat(n(stale) ? [`${n(stale)} ${n(stale) === 1 ? 'link' : 'links'} stale`] : []).join(' · ');
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
    if (!['PLAYING', 'FINISHED'].includes(gc.state) && (gc.teams || []).includes(gc.kickingTeam)) detail.push(`kick-off T${gc.kickingTeam}`);
    // clock and rest: the same parts with the clock first, for headers that cut the end ("9:35" + "1st half · …")
    return { online: true, state: gc.state, detail: detail.join(' · '), score: `T${t0 ?? '?'} ${s0} – ${s1} T${t1 ?? '?'}`,
             clock: detail[1], rest: [detail[0], ...detail.slice(2)].join(' · '),
             title: `GameController: last packet ${gc.age ?? '?'} s ago from ${gc.source || '?'}` };
}
// A robot's GameController penalty, e.g. "Leaving the field · 23 s", or "".
export function penaltyOf(agent, gc) {
    const p = gc?.penalties?.[String(agent?.team)]?.[String(agent?.id)];
    return p ? `${p[0]} · ${p[1]} s` : '';
}

// Where the robot's own view of the game differs from the GameController's, or "". Short text for the cards and
// rows ("GC: not penalised"); long = true gives the full sentence for a title attribute.
// Only the penalty and the team number: the robots send "R" in INITIAL, READY, SET and PLAYING alike
// (DebugMessageSender), so the game state itself cannot be compared.
export function stateMismatch(agent, gc, long = false) {
    if (!gc?.state || !agent) return '';
    if (gc.teams?.length && !gc.teams.includes(agent.team)) return `T${agent.team ?? '?'} is not in this game`;
    const pen = penaltyOf(agent, gc);
    if (pen && agent.state !== 'P') return long ? 'The GC penalised this robot. The robot does not know it.' : 'robot: not penalised';
    if (!pen && agent.state === 'P') return long ? 'The robot says it is penalised. The GC does not.' : 'GC: not penalised';
    return '';
}

// Team message budget of our team. message_budget is the number of messages LEFT; 12,000 is the start value the
// simulated referee uses (sim_gc.py), assumed, not sent in the packet. {known, text, title, used: 0..100 %}
export const BUDGET_START = 12000;
export function budgetSummary(gc) {
    if (!gc?.state) return { known: false, text: 'unknown: no GameController', title: 'No GameController packet in the last 2 s', used: 0 };
    const left = gc.message_budget?.[gc.own_team_index];
    if (!(gc.own_team_index >= 0) || typeof left !== 'number') {
        return { known: false, text: 'unknown: our team is not in this game', title: `own_team in config.yaml is not one of the GC teams (${(gc.teams || []).map(t => 'T' + t).join(', ')})`, used: 0 };
    }
    return { known: true, text: `${left.toLocaleString()} messages left`, used: Math.min(100, Math.max(0, (BUDGET_START - left) / BUDGET_START * 100)),
             title: `Team messages our team can still send in this game (assumed start: ${BUDGET_START.toLocaleString()})` };
}

// Texts of one robot: two teams can both have a robot 3, so the IP counts too (texts of an older gateway have no IP).
export const robotTexts = (texts, id, ip) => (texts || []).filter(t => t.agent_id === id && (!t.ip || t.ip === (ip || '127.0.0.1')));
// The same robot: the player number AND the IP.
export const isRobot = (a, id, ip) => !!a && a.id === id && (a.ip || '127.0.0.1') === (ip || '127.0.0.1');

// Legend of the team colours that the robots send, one entry per team: "●● T5 · ● T19 blue" (a team can send two colours).
export function teamLegend(agents) {
    const teams = new Map(), primary = teamPrimary(agents);  // team number -> Map(colour -> agent), primary colour first
    for (const a of agents || []) if (!teams.has(a.team)) teams.set(a.team, new Map([[String(primary.get(a.team)).toLowerCase(), a]]));
    for (const a of agents || []) {
        if (!teams.has(a.team)) teams.set(a.team, new Map());
        teams.get(a.team).set(String(a.color).toLowerCase(), a);
    }
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
    const dot = a => `<span style="display: inline-block; width: 0.7em; height: 0.7em; border-radius: 50%; background: rgb(${teamRgb(a)}); vertical-align: -0.05em;"></span>`;
    return [...teams].sort((x, y) => (x[0] || 0) - (y[0] || 0)).map(([team, cols]) => {
        const names = [...cols.keys()].filter(c => TEAM_RGB[c]).join('/');  // GameController colour names; hex colours have none
        return `<span style="white-space: nowrap;">${[...cols.values()].map(dot).join('')} T${esc(team ?? '?')}${names ? ' ' + esc(names) : ''}</span>`;
    }).join(' · ');
}

// The primary colour of each team (Map team -> colour): the first colour, in player order, that is not white, black
// or grey; a team with only such colours keeps its first. drawRobot2D rings every robot of the team with it.
const neutral = c => { const v = rawRgb(c); return !v || Math.max(...v) - Math.min(...v) < 40; };
export function teamPrimary(agents) {
    const out = new Map();
    for (const a of [...agents || []].sort((x, y) => (x.id ?? 0) - (y.id ?? 0))) {
        const cur = out.get(a.team);
        if (cur === undefined || (neutral(cur) && !neutral(a.color))) out.set(a.team, a.color);
    }
    return out;
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

// One robot in a 2D arena: disc in its colour, a 3 px outer ring in its team's primary colour (teamPrimary: a white or
// grey robot still shows its team), heading tick from the ring, number readable on any fill.
// px = canvas pixels per CSS pixel, so the robot and its number keep their screen size. ring = selection colour or null.
// tag (optional): a short text under the disc, e.g. ".2" when two robots have the same team and number (robotName).
export function drawRobot2D(ctx, agent, x, y, px, ring, teamColor, tag = '') {
    const r = 12 * px, a = Number.isFinite(agent.angle) ? agent.angle : 0;
    if (ring) {
        ctx.strokeStyle = ring;
        ctx.lineWidth = 4 * px;
        ctx.beginPath();
        ctx.arc(x, y, r + 8 * px, 0, 2 * Math.PI);
        ctx.stroke();
    }
    ctx.fillStyle = agent.color || '#822433';
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = `rgb(${teamRgb({ color: teamColor || agent.color })})`;
    ctx.lineWidth = 3 * px;
    ctx.beginPath();
    ctx.arc(x, y, r + 1.5 * px, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2 * px;
    ctx.beginPath();  // heading: from the ring outwards, so it never crosses the number
    ctx.moveTo(x + (r + 3 * px) * Math.cos(a), y - (r + 3 * px) * Math.sin(a));
    ctx.lineTo(x + (r + 10 * px) * Math.cos(a), y - (r + 10 * px) * Math.sin(a));
    ctx.stroke();
    const c = rawRgb(agent.color);
    const lum = c ? (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 : 0;
    ctx.fillStyle = lum > 0.6 ? '#111' : '#fff';
    ctx.font = `bold ${Math.round(12 * px)}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(agent.id, x, y + px);
    ctx.textBaseline = 'alphabetic';
    if (tag) drawRobotTag2D(ctx, tag, x, y, px);
}
// The twin tag (".2") under a disc at (x, y): bold 12 px white on a dark rounded box. A page draws all tags after all
// discs, so no other disc covers one (drawRobot2D's tag argument draws it at once).
export function drawRobotTag2D(ctx, tag, x, y, px) {
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.font = `bold ${Math.round(12 * px)}px sans-serif`;
    const w = ctx.measureText(tag).width + 8 * px, h = 16 * px, top = y + 15 * px;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.85)';
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x - w / 2, top, w, h, 4 * px); else ctx.rect(x - w / 2, top, w, h);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(tag, x, top + h / 2 + px);
    ctx.restore();
}
