import { loadMode, loadScenario, overlayState, saveMode } from './simulation_config.mjs';

const STYLE = [
    '.orc-source { display:inline-flex; align-items:center; gap:6px; min-width:0; font:600 11px system-ui,sans-serif; }',
    '.orc-source select { color:#dbeafe; border:1px solid #526174; border-radius:5px; background:#202b38; padding:4px 6px; font:inherit; }',
    '.orc-source .preview { color:#67e8f9; white-space:nowrap; font-size:10px; letter-spacing:.04em; }',
    '.orc-source select:focus-visible { outline:2px solid #f59e0b; outline-offset:2px; }',
    '@media(max-width:700px) { .orc-source .preview { display:none; } }',
].join('\n');
let cssAdded = false;

export function mountSourceSwitch(host, field) {
    if (!cssAdded) {
        const style = document.createElement('style');
        style.textContent = STYLE;
        document.head.append(style);
        cssAdded = true;
    }
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Session menu');
    for (const [value, label] of [['real', 'Real session'], ['simulated', 'Simulated session…'], ['hybrid', 'Real + ghosts'], ['settings', 'Settings…']]) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.append(option);
    }
    let mode = loadMode();
    select.value = mode;
    const preview = document.createElement('span');
    preview.className = 'preview';
    preview.textContent = 'DISPLAY ONLY';
    preview.hidden = mode !== 'hybrid';
    host.classList.add('orc-source');
    host.replaceChildren(select, preview);

    select.addEventListener('change', () => {
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
        compose(liveState) {
            if (mode !== 'hybrid') return liveState;
            try {
                const state = overlayState(liveState, loadScenario(), field);
                preview.textContent = state.hybrid.scaled ? 'SCALED PREVIEW' : 'DISPLAY ONLY';
                preview.title = state.hybrid.scaled ? 'Scenario positions were scaled to fit the live field.' : 'Ghosts and cyan ball are display only.';
                return state;
            } catch (error) {
                preview.textContent = 'SCENARIO ERROR';
                preview.title = error.message;
                return liveState;
            }
        },
    };
}
