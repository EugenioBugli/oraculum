// Local layout preferences only. No gateway/control requests.
export function mountWorkspaceLayout() {
    const key = `oraculum.layout.v1:${location.pathname}`;
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch { /* private storage */ }
    if (typeof saved !== 'object' || Array.isArray(saved)) saved = {};
    const persist = () => { try { localStorage.setItem(key, JSON.stringify(saved)); } catch { /* optional */ } };
    const grid = document.querySelector('.app-workspace');
    const left = grid?.children[0] || document.getElementById('toolPanelDock');
    const right = grid?.children[2] || document.getElementById('inspectorDock');
    if (!left || !right) return;
    const style = document.createElement('style');
    style.textContent = `
      .ws-pane { position:relative; min-width:0; }
      .ws-grip { position:absolute; z-index:90; touch-action:none; user-select:none; background:transparent; }
      .ws-grip:hover,.ws-grip:focus-visible { background:#6366f180; outline:1px solid #a5b4fc; }
      .ws-grip[data-axis=x] { top:0; bottom:0; width:7px; cursor:col-resize; }
      .ws-grip[data-axis=y] { left:0; right:0; bottom:0; height:7px; cursor:row-resize; }
      .ws-pane.collapsed>.ws-grip { display:none; }
      .ws-panel { position:relative; padding-bottom:7px; min-width:0; }
      .ws-panel>.panel-title { flex-shrink:0; }
      .ws-panel>.panel-body { min-height:0; }
      .ws-fold { margin-left:auto; background:transparent; border:0; color:inherit; cursor:pointer; padding:4px 7px; }
      .ws-folded { height:auto!important; min-height:0!important; flex:0 0 auto!important; padding-bottom:0; }
      .ws-folded>:not(.panel-title) { display:none!important; }
      .ws-panel .panel-title { min-height:32px; height:auto; flex-wrap:wrap; padding-top:5px; padding-bottom:5px; }
      .joystick-panel-grid > div { min-width:0; }
      .joystick-panel-grid input[type=range] { width:100%; min-width:0; }
      #robotPanel:not(.rp-manual-on) .joystick-panel-grid { display:none!important; }
      @media(max-width:1024px) { body .app-status-bar .bar-section { flex-wrap:wrap; min-width:0; max-width:100%; } }
      @media(min-width:1025px) { .app-workspace { grid-template-columns:var(--ws-left,280px) minmax(240px,1fr) var(--ws-right,320px); } }
      @media(min-width:901px) { #toolPanelDock:not(.collapsed) { width:var(--ws-left,280px); flex-shrink:0; } #inspectorDock:not(.collapsed) { width:var(--ws-right,340px); flex-shrink:0; } }
      @media(max-width:1024px) { .app-workspace>.ws-pane>.ws-grip[data-axis=x] { display:none; } }
      @media(max-width:900px) { #toolPanelDock>.ws-grip[data-axis=x],#inspectorDock>.ws-grip[data-axis=x] { display:none; } }
    `;
    document.head.append(style);
    const defaults = {left:280, right:grid ? 320 : 340};
    const dimensions = {...defaults};
    const finite = (x, fallback) => Number.isFinite(Number(x)) ? Number(x) : fallback;
    const clamp = (n, min, max) => Math.min(Math.max(min, max), Math.max(min, n));
    function grip(parent, axis, label, read, apply, reset, sign = 1) {
        const g = document.createElement('div');
        g.className = 'ws-grip'; g.dataset.axis = axis; g.tabIndex = 0;
        g.setAttribute('role','separator'); g.setAttribute('aria-label',label);
        g.setAttribute('aria-orientation',axis === 'x' ? 'vertical' : 'horizontal');
        g.title = `${label}. Drag or use arrow keys; double-click or Home to reset.`;
        let drag = null;
        const coordinate = e => axis === 'x' ? e.clientX : e.clientY;
        g.onpointerdown = e => {
            if (drag || e.button !== 0) return;
            e.preventDefault(); g.focus(); drag = {at:coordinate(e), size:read(), id:e.pointerId};
            g.setPointerCapture(e.pointerId);
        };
        g.onpointermove = e => { if (drag && e.pointerId === drag.id) apply(drag.size + sign*(coordinate(e)-drag.at)); };
        const finish = () => { drag = null; persist(); };
        g.onpointerup = finish; g.onpointercancel = finish; g.onlostpointercapture = finish;
        g.ondblclick = () => { reset(); persist(); };
        g.onkeydown = e => {
            const delta = axis === 'x' ? {ArrowLeft:-1,ArrowRight:1}[e.key] : {ArrowUp:-1,ArrowDown:1}[e.key];
            if (delta) { e.preventDefault(); apply(read()+delta*sign*(e.shiftKey ? 40 : 10)); persist(); }
            else if (e.key === 'Home') { e.preventDefault(); reset(); persist(); }
        };
        parent.append(g); g.setAttribute('aria-valuenow',Math.round(read())); return g;
    }
    const root = grid || left.parentElement;
    const sides = [];
    for (const [name,pane,sign] of [['left',left,1],['right',right,-1]]) {
        pane.classList.add('ws-pane');
        let handle;
        const apply = (value, remember = true) => {
            const other = name === 'left' ? 'right' : 'left';
            const desktop = innerWidth > (grid ? 1024 : 900);
            const max = desktop ? Math.min(560, root.clientWidth - dimensions[other] - (grid ? 242 : 310)) : 560;
            dimensions[name] = Math.round(clamp(value,220,max));
            root.style.setProperty(`--ws-${name}`,`${dimensions[name]}px`);
            if (remember) saved[name] = dimensions[name];
            handle?.setAttribute('aria-valuenow',dimensions[name]);
            handle?.setAttribute('aria-valuemin','220');
            handle?.setAttribute('aria-valuemax',Math.max(220,max));
        };
        handle = grip(pane,'x',`Resize ${name} pane`,()=>pane.getBoundingClientRect().width,apply,()=>apply(name==='left'?280:grid?320:340),sign);
        handle.style[ name === 'left' ? 'right' : 'left' ] = '0';
        sides.push(()=>apply(finite(saved[name],defaults[name]),false));
    }
    sides.forEach(fn=>fn());
    window.addEventListener('resize',()=>sides.forEach(fn=>fn()));
    const panels = [...left.querySelectorAll('.panel-box'),...right.querySelectorAll('.panel-box')];
    panels.forEach((panel,i)=> {
        panel.classList.add('ws-panel');
        const title = panel.querySelector('.panel-title');
        const label = title?.textContent.trim().replace(/\s+/g,' ') || `Panel ${i+1}`;
        const id = panel.id || `panel-${i}`;
        let handle;
        const apply = h => {
            const height = Math.round(clamp(h,150,Math.max(180,window.innerHeight*.85)));
            panel.style.height = `${height}px`; panel.style.minHeight='0'; panel.style.flex='0 0 auto';
            saved[id] = height; handle?.setAttribute('aria-valuenow',height);
            handle?.setAttribute('aria-valuemin','150');handle?.setAttribute('aria-valuemax',Math.max(180,window.innerHeight*.85));
        };
        const original = {height:panel.style.height,minHeight:panel.style.minHeight,flex:panel.style.flex};
        const reset = () => { Object.assign(panel.style,original); delete saved[id]; handle?.setAttribute('aria-valuenow',Math.round(panel.getBoundingClientRect().height)); };
        handle = grip(panel,'y',`Resize ${label}`,()=>panel.getBoundingClientRect().height,apply,reset);
        if (saved[id] !== undefined) apply(finite(saved[id],250));
        // Primary robot controls stay open. Diagnostics can be folded without adding a separate toolbar.
        if (title && panel.id !== 'robotPanel') {
            const button=document.createElement('button'); button.type='button'; button.className='ws-fold';
            const set = folded => {
                panel.classList.toggle('ws-folded',folded); button.textContent=folded?'＋':'−';
                button.setAttribute('aria-expanded',String(!folded)); button.setAttribute('aria-label',`${folded?'Expand':'Collapse'} ${label}`);
                saved[`${id}:folded`]=folded;
            };
            button.onclick=()=>{set(!panel.classList.contains('ws-folded'));persist();}; title.append(button);
            set(saved[`${id}:folded`] ?? /DRAWINGS|BUDGET/.test(label));
        }
    });
}
