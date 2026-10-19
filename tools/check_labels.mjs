// Self-check of placeLabels (src/static/circus_view.js), the R<id> label layout of all 3D engines.
// Run: node tools/check_labels.mjs [path of circus_view.js]   (exit 0 = pass)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(process.argv[2] || new URL('../src/static/circus_view.js', import.meta.url), 'utf8');
const { placeLabels } = await import('data:text/javascript,' + encodeURIComponent(src));

const boxes = (items, lh) => items.map(it => ({ x: it.left, y: it.y - it.up - lh, w: 2 * lh, h: lh }));
function check(items, w, h, lh, top = 0, avoid = []) {
    const bar = typeof top === 'number' ? { left: 0, right: w, bottom: top } : top;
    const b = boxes(placeLabels(items, w, h, lh, top, avoid), lh);
    for (const [i, p] of b.entries()) {
        assert.ok(p.x >= 0 && p.x + p.w <= w && p.y >= 0 && p.y + p.h <= h, `label ${i} outside: ${JSON.stringify(p)}`);
        assert.ok(!(p.x < bar.right && bar.left < p.x + p.w && p.y < bar.bottom), `label ${i} under the bar: ${JSON.stringify(p)}`);
        for (const a of avoid) {
            assert.ok(!(p.x < a.right && a.left < p.x + p.w && p.y < a.bottom && a.top < p.y + p.h), `label ${i} covers ${JSON.stringify(a)}`);
        }
        for (const q of b.slice(i + 1)) {
            assert.ok(!(p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h), `overlap ${JSON.stringify([p, q])}`);
        }
    }
    return items;
}
// 10 robots at the top edge of a 390x200 view, in two groups of 5 (the old limit of two steps down overlapped)
check(Array.from({ length: 10 }, (_, i) => ({ x: i < 5 ? 100 : 280, y: 10, z: i })), 390, 200, 26);
check(Array.from({ length: 10 }, (_, i) => ({ x: 20 + 39 * i, y: 10, z: i })), 390, 200, 26);
// the same column of 6 under a 56 px top bar
check(Array.from({ length: 6 }, (_, i) => ({ x: 195, y: 5 + i, z: i })), 390, 300, 26, 56);
// labels in one column that are off the label-height grid, then a far one clamped at the top (round-2 overlap)
check([26, 64, 114, 156, 20].map((y, i) => ({ x: -50, y, z: i })), 678, 728, 26);
// a bar over part of the width (dashboard GC pill at 844x390): a label beside it stays on its anchor
const pill = { left: 297, right: 503, bottom: 31 };
const [beside] = check([{ x: 100, y: 40, z: 0 }, { x: 400, y: 40, z: 1 }], 800, 314, 26, pill);
assert.equal(beside.up, 0, 'label beside the pill moved');
// the team ball just above a robot's anchor: the label goes over the ball, and only that label moves
const ball = { left: 192, right: 208, top: 80, bottom: 96 };
const far = { x: 100, y: 100, z: 1 }, onBall = { x: 200, y: 100, z: 0 };
check([far, onBall], 400, 300, 26, 0, [ball]);
assert.equal(far.up, 0, 'label away from the ball moved');
assert.ok(onBall.up >= 26, 'label over the ball did not move');
// leader line: only for a label lifted by a label height or more, from its bottom centre to its anchor
const { leaderLines } = await import('data:text/javascript,' + encodeURIComponent(src));
assert.equal(leaderLines([far], 26), '');
assert.match(leaderLines([onBall], 26), new RegExp(`x1="${(onBall.left + 26).toFixed(1)}" y1="${(100 - onBall.up).toFixed(1)}" x2="200.0" y2="100.0"`));
console.log('placeLabels: ok');
