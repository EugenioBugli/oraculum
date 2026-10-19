// "Circus (exact)" 3D view of index.html and dashboard.html.
// The B2 renderer (renderer/README.md) runs MuJoCo 3.3.3 and its classic renderer, unchanged, in WebAssembly
// and replays the frame on WebGL2, with circus's view options, camera and 4x antialiasing: the image is the one
// the circus window shows, of the scene circus's own SceneParser exported. /state drives robots, joints,
// jersey numbers and the ball. R<id> labels and debug drawings go on an SVG layer over it, placed with
// MuJoCo's own camera matrices. Not a 2D canvas: WebKit (Playwright 1.58, iPhone 14 profile) showed a 2D
// canvas that is redrawn every frame at twice its size on a 3x screen (measured; the first draw was right).
// Files (git-ignored; tools/fetch_circus_scene.py fetches them from the CI release):
//   /static/circus/                        b2.js, b2_engine.js, b2_engine.wasm
//   /static/models/circus_scene_<scene>/   scene package: files.json, scene.xml, scene_index.json, assets/

const BASE = '/static/circus';
const LABEL_Z = 1.3;  // m: label anchor just above the head of the T1 (1.18 m tall)
const DRAW_Z = 0.02;  // m: debug drawings just above the field, as in the Three.js engines

// R<id> label layout, shared by all engines: a label that would overlap a nearer one is lifted by one
// label height per overlap, and every badge is kept inside the view.
// items: [{x, y, z}] anchors in CSS pixels, z = depth (smaller = nearer); w, h: view size; lh: label height;
// top: a bar over the top of the view that labels must not go under: a height in px (full width), or
// {left, right, bottom} in view px for a bar over part of the width (dashboard GC pill).
// avoid: [{left, right, top, bottom}] boxes in view px that labels must not cover (the team ball).
// Sets item.left (left edge of the badge) and item.up (pixels the badge bottom is lifted above the anchor).
// ponytail: O(n²) over the labels, fine for the few robots on a field. At the top edge a badge steps down
// to the first free place; it overlaps only when the column is full down to the bottom of the view.
export function placeLabels(items, w, h, lh, top = 0, avoid = []) {
    const lw = 2 * lh;
    items.sort((a, b) => a.z - b.z);  // nearest first: nearer labels keep their place
    const placed = [...avoid];
    for (const it of items) {
        const left = Math.min(Math.max(it.x - lw / 2, 0), w - lw);
        const bar = typeof top === 'number' ? top : (left < top.right && top.left < left + lw ? top.bottom : 0);
        let up = Math.max(0, it.y - h);  // a robot below the view starts at its edge
        const hits = () => placed.some(p => left < p.right && p.left < left + lw
            && it.y - up - lh < p.bottom && p.top < it.y - up);
        while (hits()) up += lh;
        if (it.y - up - lh < bar) {  // past the top edge: clamp, then step down to a free place
            up = it.y - lh - bar;
            while (hits() && it.y - up + lh <= h) up -= lh;
        }
        placed.push({ left, right: left + lw, top: it.y - up - lh, bottom: it.y - up });
        it.left = left;
        it.up = up;
    }
    return items;
}

// SVG of a 1 px leader line from the bottom centre of each label that placeLabels lifted by a label height
// or more to its anchor, so a lifted label still points at its robot. Shared by all engines.
export function leaderLines(items, lh) {
    return items.filter(it => it.up >= lh).map(it => `<line x1="${(it.left + lh).toFixed(1)}" y1="${(it.y - it.up).toFixed(1)}"`
        + ` x2="${it.x.toFixed(1)}" y2="${it.y.toFixed(1)}" stroke="#00d2ff" stroke-opacity="0.8" stroke-width="1"/>`).join('');
}

// Style of the one-line notes over a 3D view (circus status line, fallback note of the pages).
const NOTE_STYLE = 'position:absolute; left:8px; bottom:8px; max-width:calc(100% - 16px); padding:2px 8px;'
    + ' border-radius:4px; background:rgba(0,0,0,0.65); color:#fbbf24; font:600 12px/1.4 system-ui,sans-serif; pointer-events:none;';

// One-line note at the bottom of parent (a positioned element); text '' removes it.
export function showNote(parent, text) {
    let n = parent.querySelector(':scope > .circus-note');
    if (!text) return n && n.remove();
    if (!n) {
        n = Object.assign(document.createElement('div'), { className: 'circus-note' });
        n.style.cssText = NOTE_STYLE;
        parent.appendChild(n);
    }
    n.textContent = text;
}

function loadScript(src) {
    return new Promise((ok, fail) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = ok;
        s.onerror = () => fail(Object.assign(new Error(`cannot load ${src}`), { code: 'B2_ENGINE' }));
        document.head.appendChild(s);
    });
}

// Field points of a debug drawing (coordinates as in tools/udp_sender.py); null: not drawn in 3D.
// A point gives its centre and a point on its rim (the radius).
function shape(dr) {
    const c = dr.coords;
    if ((dr.frame || 'field') !== 'field' || !c || c.length < 2) return null;
    const ring = (x, y, r, a0, a1, n) => Array.from({ length: n + 1 }, (_, i) => {
        const t = a0 + (a1 - a0) * i / n;
        return [x + r * Math.cos(t), y + r * Math.sin(t)];
    });
    if (dr.type === 'point') return [[c[0], c[1]], [c[0] + (dr.size || 0.05), c[1]]];
    if (dr.type === 'circle') return ring(c[0], c[1], dr.size || 0.15, 0, 2 * Math.PI, 64);
    if (dr.type === 'line' && c.length >= 4) return [[c[0], c[1]], [c[2], c[3]]];
    if (dr.type === 'box' && c.length >= 4) {
        const [x, y, w, h] = c;
        return [[x - w / 2, y - h / 2], [x + w / 2, y - h / 2], [x + w / 2, y + h / 2], [x - w / 2, y + h / 2], [x - w / 2, y - h / 2]];
    }
    if (dr.type === 'arc') return ring(c[0], c[1], c[2] || dr.size || 0.2, (c[3] || 0) * Math.PI / 180, (c[4] || 360) * Math.PI / 180, 16);
    return null;
}

// container: an empty element of the page; it gets the WebGL2 canvas, the SVG overlay and a status line.
// opts: scene (default 'maximus_5v5'), badge(text) -> canvas of an R<id> label, labelPx (label height),
// hiddenPaths (Set of the drawing paths the user turned off), labelTop() -> placeLabels top (px or {left, right, bottom}).
// Rejects with e.code 'B2_NO_WEBGL2', 'B2_ENGINE' or 'B2_SCENE' (see b2.js); the page then falls back.
export async function createCircusView(container, opts) {
    const scene = `/static/models/circus_scene_${opts.scene || 'maximus_5v5'}`;
    const layer = 'position:absolute; inset:0; width:100%; height:100%;';
    const canvas = document.createElement('canvas');
    canvas.style.cssText = layer + 'display:block;';
    canvas.title = 'Drag: move · Shift+drag or middle drag: rotate · Wheel: zoom · Double-click: circus view';
    const overlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg');  // user units = CSS pixels
    overlay.style.cssText = layer + 'pointer-events:none; overflow:hidden;';
    const status = document.createElement('div');
    status.style.cssText = NOTE_STYLE;
    status.textContent = 'Loading the circus scene…';
    container.replaceChildren(canvas, overlay, status);
    let v, index;
    try {
        if (!window.B2Viewer) await loadScript(`${BASE}/b2.js`);
        [v, index] = await Promise.all([
            // ponytail: preserve = preserveDrawingBuffer. Without it, headless Chrome on the RTX 4050 showed 6 of 36
            // frames black or half drawn (readPixels was right); with it, 0 of 210 (2026-10-12). It can cost one copy
            // per frame; measured: no cost above the noise (Android emulator 60 fps, 5.2 ms per synced frame against
            // 5.9 ms without; Intel Arc 60 fps at 1280x800). The CI pixel test (renderer/shot.py) also sets it.
            window.B2Viewer.create(canvas, { scene, engineUrl: BASE, preserve: true }),
            fetch(`${scene}/scene_index.json`).then(r => {
                if (!r.ok) throw Object.assign(new Error(`scene_index.json: HTTP ${r.status}`), { code: 'B2_SCENE' });
                return r.json();
            }),
        ]);
    } catch (e) {
        container.replaceChildren();
        throw e;
    }
    status.textContent = '';
    status.hidden = true;

    // Robot slots of the scene (5 per team in maximus_5v5), each showing at most one agent of /state.
    const slots = new Map(v.listRobots().map(r => [r.name, { team: r.team, number: r.number, key: null, agent: null }]));
    for (const name of slots.keys()) v.setRobotVisible(name, false);

    // Team of an agent: 'red' or 'blue' in agent.color or agent.team (the framework sends color names);
    // a hex colour goes to the nearer circus jersey colour (scene_index.json); any other team number or
    // colour name: the first one seen plays red, the next blue.
    const teamRgb = Object.fromEntries(index.robots.map(r => [r.team, r.trunk_rgba.split(' ').slice(0, 3).map(c => 255 * c)]));
    const otherTeams = new Map();
    // All robots of one team number share the jersey of its first robot (fake or mixed colours such as black
    // and white must not move a robot into the other team's slots); a second team gets the other jersey.
    const byTeam = new Map();
    function teamOf(a) {
        const n = typeof a.team === 'number' && a.team > 0 ? a.team : null;
        if (n !== null && byTeam.has(n)) return byTeam.get(n);
        let t = jerseyOf(a);
        if (n !== null) {
            if ([...byTeam.values()].includes(t)) t = Object.keys(teamRgb).find(x => x !== t) || t;
            byTeam.set(n, t);
        }
        return t;
    }
    function jerseyOf(a) {
        for (const t of [a.color, a.team]) if (typeof t === 'string' && teamRgb[t.toLowerCase()]) return t.toLowerCase();
        const hex = /^#([0-9a-f]{6})$/i.exec(a.color || '');
        if (hex) {
            const rgb = [0, 2, 4].map(i => parseInt(hex[1].slice(i, i + 2), 16));
            const d = (t) => Math.hypot(...teamRgb[t].map((c, i) => c - rgb[i]));
            return Object.keys(teamRgb).reduce((best, t) => (d(t) < d(best) ? t : best));
        }
        const k = String(a.team ?? a.color);
        if (!otherTeams.has(k)) otherTeams.set(k, otherTeams.size % 2 ? 'blue' : 'red');
        return otherTeams.get(k);
    }

    // A slot that a new robot takes starts from the scene's rest pose (joints the robot does not send).
    // ponytail: reads B2Viewer internals (robots, qpos0); add a B2Viewer method if more code needs it.
    const resetJoints = (name) => {
        const q0 = v.qpos0;
        v.setJoints(name, Object.fromEntries(Object.entries(v.robots.get(name).joints).map(([j, a]) => [j, q0[a]])));
    };

    let last = { agents: [], drawings: [] };
    function update(state) {
        last = state;
        if (!v.ready) return;  // context restore in progress: b2restored applies the last state
        const present = new Map();
        for (const a of state.agents || []) {
            if (Number.isFinite(a.x) && Number.isFinite(a.y)) present.set(`${a.ip || ''}|${a.id}`, a);
        }
        const kept = new Set();
        for (const s of slots.values()) {  // a robot keeps its slot while it is present and in the same team
            const a = s.key && present.get(s.key);
            if (a && teamOf(a) === s.team) kept.add(s.key); else s.key = null;
        }
        const unplaced = [];
        for (const [key, a] of present) {
            if (kept.has(key)) continue;
            const team = teamOf(a);
            const free = [...slots].filter(([, s]) => s.team === team && !s.key);
            const pick = free.find(([, s]) => s.number === a.id) || free[0];  // prefer the slot with its number
            if (!pick) { unplaced.push(`${team} R${a.id}`); continue; }
            pick[1].key = key;
            resetJoints(pick[0]);
        }
        for (const [name, s] of slots) {
            s.agent = (s.key && present.get(s.key)) || null;
            v.setRobotVisible(name, !!s.agent);
            if (!s.agent) continue;
            const a = s.agent;
            // field frame = circus world frame: x towards the +x goal, y left, angle about +z (0 = +x)
            v.setRobotState(name, { x: a.x, y: a.y, yaw: Number.isFinite(a.angle) ? a.angle : 0 });
            if (a.joints) v.setJoints(name, a.joints);
            v.setNumber(name, a.id);  // circus draws 1..9; other ids show no number
        }
        const b = state.ball;
        const ball = !!b && Number.isFinite(b.x) && Number.isFinite(b.y);
        v.setBallVisible(ball);
        if (ball) v.setBall(b.x, b.y);
        const text = unplaced.length ? `Not drawn, no free robot in the circus scene: ${unplaced.join(', ')}` : '';
        if (text !== status.textContent) {
            if (text) console.warn('[Circus]', text);
            status.textContent = text;
            status.hidden = !text;
        }
        schedule();
    }

    let pending = false;
    // Default view: circus's camera (lookat, azimuth, elevation). On views narrower than circus's 16:9 window
    // the camera moves back so the whole field fits (user decision 2026-10-12); a resize or rotation keeps the
    // user's zoom relative to that fit. Double-click / double-tap returns here.
    const fitFactor = (w, h) => Math.max(1, (16 / 9) / (w / h));
    let fitted = 1;
    function resetView() {
        const [lookat, dist, az, el] = window.B2Viewer.CIRCUS_CAMERA;
        fitted = fitFactor(container.clientWidth || 16, container.clientHeight || 9);
        v.setCamera(lookat, dist * fitted, az, el);
    }
    function schedule() {
        if (pending) return;
        pending = true;
        requestAnimationFrame(() => { pending = false; frame(); });
    }
    function frame() {
        const w = container.clientWidth, h = container.clientHeight;
        if (!w || !h) return;  // hidden (2D view or another engine): the ResizeObserver draws on return
        const f = fitFactor(w, h);
        if (f !== fitted) {  // new view shape: same zoom relative to the field fit
            const c = v.getCamera();
            v.setCamera(c.lookat, c.distance * f / fitted, c.azimuth, c.elevation);
            fitted = f;
        }
        const k = Math.min(window.devicePixelRatio || 1, 2);  // as the Three.js engines
        const cw = Math.round(w * k), ch = Math.round(h * k);
        if (canvas.width !== cw || canvas.height !== ch) {
            canvas.width = cw;
            canvas.height = ch;
        }
        if (v.render()) drawOverlay(w, h);  // null while loading or with the WebGL context lost
    }
    resetView();
    new ResizeObserver(frame).observe(container);  // synchronous: no blank frame after a resize

    const badges = new Map();  // label text -> PNG data URL of the page's badge
    const f1 = (n) => n.toFixed(1);
    function drawOverlay(w, h) {
        const m = v.getViewProjection().viewProj;
        // field point -> [x, y] in CSS pixels and the clip w (distance); null behind the camera
        const P = (x, y, z) => {
            const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
            if (!(cw > 0.01)) return null;
            return [((m[0] * x + m[4] * y + m[8] * z + m[12]) / cw + 1) / 2 * w,
                    (1 - (m[1] * x + m[5] * y + m[9] * z + m[13]) / cw) / 2 * h, cw];
        };
        // field polyline -> pieces in CSS pixels, cut where it passes behind the camera (clip w <= E)
        const E = 0.02, cw = (q) => m[3] * q[0] + m[7] * q[1] + m[11] * DRAW_Z + m[15];
        const cut = (pts) => {
            const pieces = [];
            let piece = null;
            for (let i = 1; i < pts.length; i++) {
                const b = pts[i - 1], a = pts[i], wb = cw(b), wa = cw(a);
                if (wb <= E && wa <= E) { piece = null; continue; }
                const t = (E - wb) / (wa - wb), mid = [b[0] + t * (a[0] - b[0]), b[1] + t * (a[1] - b[1])];
                if (!piece || wb <= E) pieces.push(piece = [P(...(wb <= E ? mid : b), DRAW_Z)]);
                piece.push(P(...(wa <= E ? mid : a), DRAW_Z));
                if (wa <= E) piece = null;
            }
            return pieces;
        };
        let svg = '';
        for (const dr of last.drawings || []) {  // debug drawings, field frame
            if (dr.path && opts.hiddenPaths && opts.hiddenPaths.has(dr.path)) continue;
            const pts = shape(dr);
            if (!pts) continue;
            const c = dr.color || [255, 255, 255], col = `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
            if (dr.type === 'point') {
                const px = pts.map(([x, y]) => P(x, y, DRAW_Z));
                if (px.some(p => !p)) continue;
                const r = Math.max(2, Math.hypot(px[1][0] - px[0][0], px[1][1] - px[0][1]));
                svg += `<circle cx="${f1(px[0][0])}" cy="${f1(px[0][1])}" r="${f1(r)}" fill="${col}" fill-opacity="0.55"/>`;
                continue;
            }
            for (const px of cut(pts)) {
                svg += `<polyline points="${px.map(p => f1(p[0]) + ',' + f1(p[1])).join(' ')}" fill="none" stroke="${col}"`
                    + ` stroke-opacity="0.8" stroke-width="2" stroke-linejoin="round"${dr.dash ? ' stroke-dasharray="5 4"' : ''}/>`;
            }
        }
        const items = [];
        for (const s of slots.values()) {
            const p = s.agent && P(s.agent.x, s.agent.y, LABEL_Z);
            if (p) items.push({ x: p[0], y: p[1], z: p[2], text: `R${s.agent.id}` });
        }
        // Labels must not cover the team ball: its screen box (radius = ball radius x projection scale / distance;
        // the norm of viewProj's y row is the projection's y scale), at least 4 px
        const avoid = [], b = last.ball, br = (v.ball && v.ball.radius) || 0.11;
        const bp = b && Number.isFinite(b.x) && Number.isFinite(b.y) && P(b.x, b.y, br);
        if (bp) {
            const r = Math.max(4, br * Math.hypot(m[1], m[5], m[9]) * h / 2 / bp[2]);
            avoid.push({ left: bp[0] - r, right: bp[0] + r, top: bp[1] - r, bottom: bp[1] + r });
        }
        const lh = opts.labelPx || 26;
        let tags = '';
        for (const it of placeLabels(items, w, h, lh, opts.labelTop ? opts.labelTop() : 0, avoid)) {
            if (!badges.has(it.text)) badges.set(it.text, opts.badge(it.text).toDataURL());
            tags += `<image href="${badges.get(it.text)}" x="${f1(it.left)}" y="${f1(it.y - it.up - lh)}" width="${2 * lh}" height="${lh}"/>`;
        }
        overlay.innerHTML = svg + leaderLines(items, lh) + tags;  // a line that passes a lower label goes under it
    }

    // Camera: mouse as in circus (B2Viewer.attachControls); touch: one finger rotates, two fingers move
    // and pinch-zoom. Double-click or double-tap: back to the circus camera.
    v.attachControls(canvas, schedule);
    const reset = () => { resetView(); schedule(); };
    canvas.addEventListener('dblclick', reset);
    let tap = null, down = null;  // tap: the last touch that was a tap (short, did not move)
    canvas.addEventListener('pointerdown', (e) => {
        if (e.pointerType !== 'touch' || !e.isPrimary) return;
        down = { t: e.timeStamp, x: e.clientX, y: e.clientY };
        if (tap && e.timeStamp - tap.t < 300 && Math.hypot(e.clientX - tap.x, e.clientY - tap.y) < 30) {
            tap = down = null;
            reset();
        }
    });
    canvas.addEventListener('pointerup', (e) => {
        if (e.pointerType !== 'touch' || !e.isPrimary || !down) return;
        tap = e.timeStamp - down.t < 250 && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 10 ? down : null;
        down = null;
    });
    const setStatus = (text) => { status.textContent = text; status.hidden = !text; };
    canvas.addEventListener('webglcontextlost', () => {  // b2.js reloads the scene on restore (a few seconds)
        overlay.innerHTML = '';
        setStatus('Restoring the 3D view…');
    });
    canvas.addEventListener('b2restored', () => { setStatus(''); update(last); });

    frame();
    return { viewer: v, update, reset, render: schedule, slots };
}
