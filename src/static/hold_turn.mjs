// A bounded hold-to-turn input. The existing manual /control loop provides the dead-man packet stream.
export function mountTurnHold(left, right) {
    let held = 0;
    let pointer = null;
    const stop = () => { held = 0; pointer = null; };
    for (const [button, direction] of [[left, 0.35], [right, -0.35]]) {
        button.style.touchAction = 'none';
        button.addEventListener('pointerdown', event => {
            if (button.disabled || pointer !== null) return;
            event.preventDefault();
            pointer = event.pointerId;
            held = direction;
            try { button.setPointerCapture(event.pointerId); } catch { /* window listeners also release */ }
        });
        for (const name of ['pointerup', 'pointercancel', 'lostpointercapture', 'pointerleave']) {
            button.addEventListener(name, event => { if (event.pointerId === pointer) stop(); });
        }
    }
    window.addEventListener('pointerup', event => { if (event.pointerId === pointer) stop(); });
    window.addEventListener('pointercancel', event => { if (event.pointerId === pointer) stop(); });
    window.addEventListener('blur', stop);
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    return {
        value: () => held,
        stop,
        setEnabled(enabled) {
            left.disabled = right.disabled = !enabled;
            if (!enabled) stop();
        },
    };
}
