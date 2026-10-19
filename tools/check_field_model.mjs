// Self-check of src/static/field_model.js (team colours, belief drawings, field lines):  node tools/check_field_model.mjs
import assert from 'node:assert/strict';
import { beliefDrawings, fieldLines, teamRgb } from '../src/static/field_model.js';

const rgb = (color) => teamRgb({ color }).join(',');
assert.equal(rgb('#000000'), '140,140,140');  // black team: visible grey on the dark field
assert.equal(rgb('#822433'), '140,46,61');
assert.equal(rgb('red'), '229,72,77');
assert.equal(rgb('#ffffff'), '255,255,255');
assert.equal(rgb('?'), '159,164,178');

const d = beliefDrawings([
    { id: 9, x: 3, y: 0, color: 'red', ball: { x: 4, y: 1 }, obstacles: [{ x: 4.5, y: -1 }, { x: null, y: 1 }] },
    { id: 1, x: NaN, y: 0, ball: { x: 0, y: 0 } },  // no pose: no beliefs
]);
assert.deepEqual(d.map((x) => [x.type, x.path, x.coords.join()]), [
    ['line', 'beliefs/ball', '3,0,4,1'], ['point', 'beliefs/ball', '4,1'], ['circle', 'beliefs/obstacles', '4.5,-1']]);
assert.ok(d[0].dash && d[2].dash && !d[1].dash);

const lines = fieldLines({ width: 14, height: 9, center_radius: 1.5, goal_area_width: 1, goal_area_height: 4,
    penalty_area_width: 3, penalty_area_height: 6.5, penalty_mark_distance: 2.1 });
assert.equal(lines.length, 11);  // border, halfway, circle, 2 x (goal area, penalty area, 2 mark strokes)
assert.deepEqual(lines[0][2], [7, 4.5]);
console.log('field_model self-check OK');
assert.equal(rgb('yellow'), '250,204,21');  // GameController colour names, as the robots send them
assert.equal(rgb('black'), '140,140,140');
assert.equal(rgb('gray'), '140,140,140');
console.log('colour names OK');
