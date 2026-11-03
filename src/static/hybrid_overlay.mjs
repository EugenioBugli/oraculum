import { loadMode, loadScenario, overlayState, saveMode } from './simulation_config.mjs';

const STYLE = [
    '.orc-source { display:inline-flex; align-items:center; gap:6px; min-width:0; font:600 11px system-ui,sans-serif; }',
    '.orc-source select { color:#dbeafe; border:1px solid #526174; border-radius:5px; background:#202b38; padding:4px 6px; font:inherit; }',
    '.orc-source .preview { color:#67e8f9; white-space:nowrap; font-size:10px; letter-spacing:.04em; }',
    '.orc-source select:focus-visible { outline:2px solid #f59e0b; outline-offset:2px; }',
    '@media(max-width:700px) { .orc-source .preview { display:none; } }',
].join('\n');
let cssAdded = false;
const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

export function advanceGhostPose(pose, { vx = 0, vy = 0, vtheta = 0 }, dt, field) {
    // Preview speeds are deliberately modest. Inputs use the same robot-relative signs as Manual.cpp.
    const forward = clamp(Number(vx) || 0, -1, 1) * 0.35;
    const side = clamp(Number(vy) || 0, -1, 1) * 0.25;
    const turn = clamp(Number(vtheta) || 0, -1, 1) * 0.8;
    const c = Math.cos(pose.angle), s = Math.sin(pose.angle);
    return {
        x: clamp(pose.x + (c * forward - s * side) * dt, -field.width / 2 + 0.15, field.width / 2 - 0.15),
        y: clamp(pose.y + (s * forward + c * side) * dt, -field.height / 2 + 0.15, field.height / 2 - 0.15),
        angle: Math.atan2(Math.sin(pose.angle + turn * dt), Math.cos(pose.angle + turn * dt)),
    };
}

export function mountSourceSwitch(host, field) {
    if (!cssAdded) {
        const style = document.createElement('style');
        style.textContent = STYLE;
        document.head.append(style);
        cssAdded = true;
    }
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Session menu');
    for (const [value, label] of [['real', 'Real session'], ['simulated', 'Simulated session…'], ['hybrid', 'Real + ghosts'], ['operations', 'Operations…'], ['settings', 'Settings…']]) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.append(option);
    }
    let mode = loadMode();
    const ghostPose = new Map();
    let ghostIps = new Set();
    let scenarioSnapshot = '';
    select.value = mode;
    const preview = document.createElement('span');
    preview.className = 'preview';
    preview.textContent = 'DISPLAY ONLY';
    preview.hidden = mode !== 'hybrid';
    host.classList.add('orc-source');
    host.replaceChildren(select, preview);

    select.addEventListener('change', () => {
        if (select.value === 'operations') {
            location.href = '/operations.html';
            return;
        }
        if (select.value === 'simulated' || select.value === 'settings') {
            location.href = '/simulation.html?mode=' + select.value;
            return;
        }
        mode = saveMode(select.value);
        const url = new URL(location.href);
        url.searchParams.delete('source');
        history.replaceState(null, '', url);
        preview.hidden = mode !== 'hybrid';
    });
    window.addEventListener('storage', (event) => {
        if (event.key === 'oraculum_source_mode_v1') {
            mode = loadMode();
            select.value = mode;
            preview.hidden = mode !== 'hybrid';
        }
    });

    return {
        mode: () => mode,
        isLocalGhost: (ip) => mode === 'hybrid' && ghostIps.has(ip),
        poseOf(ip) {
            if (mode !== 'hybrid' || !ghostIps.has(ip)) return null;
            const pose = ghostPose.get(ip);
            return pose ? { x: pose.x, y: pose.y, angle: pose.angle } : null;
        },
        driveGhost(ip, { vx = 0, vy = 0, vtheta = 0 }, now = performance.now()) {
            if (mode !== 'hybrid' || !ghostIps.has(ip)) return false;
            const pose = ghostPose.get(ip);
            if (!pose) return false;
            const elapsed = (now - (pose.lastAt ?? now)) / 1000;
            const dt = elapsed > 0.5 ? 0 : clamp(elapsed, 0, 0.2);
            pose.lastAt = now;
            // Browser-local kinematic preview, in the same robot-relative directions as Manual.cpp.
            // It never sends a gateway command and does not model the firmware's gait or balance.
            Object.assign(pose, advanceGhostPose(pose, { vx, vy, vtheta }, dt, field));
            return true;
        },
        compose(liveState) {
            if (mode !== 'hybrid') { ghostIps.clear(); return liveState; }
            try {
                const scenario = loadScenario();
                const snapshot = JSON.stringify(scenario);
                if (snapshot !== scenarioSnapshot) { ghostPose.clear(); scenarioSnapshot = snapshot; }
                const state = overlayState(liveState, scenario, field);
                ghostIps = new Set();
                for (const ghost of state.agents.filter(a => a.simulated && a.ip?.startsWith('sim.'))) {
                    ghostIps.add(ghost.ip);
                    if (!ghostPose.has(ghost.ip)) ghostPose.set(ghost.ip, { x: ghost.x, y: ghost.y, angle: ghost.angle, lastAt: null });
                    const pose = ghostPose.get(ghost.ip);
                    Object.assign(ghost, { x: pose.x, y: pose.y, angle: pose.angle, state: 'Manual preview' });
                }
                preview.textContent = state.hybrid.scaled ? 'SCALED GHOST' : 'GHOST JOYSTICK';
                preview.title = state.hybrid.scaled ? 'Ghost positions were scaled to fit the live field; their joystick preview stays local.' : 'Ghost joystick preview stays in this browser; the cyan ball is display only.';
                return state;
            } catch (error) {
                ghostIps.clear();
                preview.textContent = 'SCENARIO ERROR';
                preview.title = error.message;
                return liveState;
            }
        },
    };
}
