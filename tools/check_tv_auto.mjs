// Self-check of the AUTO shots of the TV view (src/static/tv_auto.js): goalTeam, nearestRobot, nextShot, robotName, robotTag.
// Run: node tools/check_tv_auto.mjs   (exit 0 = pass)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../src/static/tv_auto.js', import.meta.url), 'utf8');
const { goalTeam, nearestRobot, nextShot, robotName, robotTag } = await import('data:text/javascript,' + encodeURIComponent(src));

// goalTeam: each side, and no change
assert.equal(goalTeam([0, 0], [1, 0], [19, 5]), 19);
assert.equal(goalTeam([1, 0], [1, 1], [19, 5]), 5);
assert.equal(goalTeam([1, 1], [1, 1], [19, 5]), null);
assert.equal(goalTeam(undefined, [0, 0], [19, 5]), null);

const agents = [{ ip: '127.0.0.1', id: 1, team: 19, x: -4, y: 0 }, { ip: '127.0.0.1', id: 2, team: 19, x: 2, y: 1 },
                { ip: '127.0.0.1', id: 3, team: 5, x: 3, y: 1 }];
const gc = { state: 'PLAYING', teams: [19, 5], score: [0, 0], kickingTeam: 19, set_play_name: '', penalties: {} };
const state = (g = {}) => ({ agents, ball: { x: 2.5, y: 1 }, gamecontroller: { ...gc, ...g } });
const names = { 19: 'SPQR', 5: 'B-Human' };

// nearestRobot: the team's robot nearest to the ball; no robot of that team -> ""
assert.equal(nearestRobot(19, state()), '127.0.0.1|2');
assert.equal(nearestRobot(5, state()), '127.0.0.1|3');
assert.equal(nearestRobot(7, state()), '');
assert.equal(nearestRobot(19, { agents }), '127.0.0.1|1');  // no ball: lowest number

// A tiny TV: events in id order, the shot replaces the current one as the page does
function tv(lastPhase = 'INITIAL') {
    const ctx = { scoreSeen: [0, 0], lastPhase, current: null, now: 0, names };
    return { ctx, feed(ev, st, now) {
        ctx.now = now;
        const s = nextShot(ev, st, ctx);
        if (s) ctx.current = { ...s, until: now + s.hold_s };
        return s;
    } };
}

// GOAL: team from the score change, camera of its robot nearest the ball, banner names team and score
let t = tv('PLAYING');
let s = t.feed({ type: 'GOAL', robot: '', text: 'goal team 19 (1-0)' }, state({ score: [1, 0] }), 0);
assert.equal(s.kind, 'goal');
assert.deepEqual([s.view, s.robots, s.prio, s.hold_s], ['camera', ['127.0.0.1|2'], 3, 10]);
assert.equal(s.big.title, 'GOAL · SPQR');
assert.equal(s.big.sub, 'SPQR 1 – 0 B-Human');
assert.deepEqual(t.ctx.scoreSeen, [1, 0]);
// the same score seen again (a replayed event): no second goal
assert.equal(t.feed({ type: 'GOAL', robot: '' }, state({ score: [1, 0] }), 1), null);

// One referee goal during PLAYING: PHASE READY then GOAL in one batch -> the goal wins; READY cannot cut it
t = tv('PLAYING');
t.feed({ type: 'PHASE', text: 'READY' }, state({ state: 'READY', score: [0, 1], kickingTeam: 19 }), 0);
assert.equal(t.ctx.current.kind, 'ready');
t.feed({ type: 'GOAL', robot: '' }, state({ state: 'READY', score: [0, 1], kickingTeam: 19 }), 0);
assert.equal(t.ctx.current.kind, 'goal');
assert.equal(t.ctx.current.big.title, 'GOAL · B-Human');
assert.equal(t.feed({ type: 'PENALTY', robot: 'T5 R3', text: 'T5 R3: Pushing' }, state({ penalties: { 5: { 3: ['Pushing', 30] } } }), 4), null);
// after the hold, a weaker shot replaces it
assert.equal(t.feed({ type: 'PENALTY', robot: 'T5 R3', text: 'T5 R3: Pushing' }, state({ penalties: { 5: { 3: ['Pushing', 30] } } }), 11).banner,
             'B-Human #3: Pushing');
// equal priority replaces at once
assert.equal(t.feed({ type: 'SETPLAY', text: 'CORNER KICK for team 19' }, state({ set_play_name: 'CORNER KICK' }), 12).banner,
             'Corner kick · SPQR');
// "back in play" and free text are never shown
assert.equal(t.feed({ type: 'PENALTY', robot: 'T5 R3', text: 'T5 R3: back in play' }, state(), 20), null);
assert.equal(t.feed({ type: 'MARK', robot: '', text: 'secret note' }, state(), 20), null);

// Kick-off only after SET: SET -> PLAYING gives split; READY -> PLAYING does not; a set play does not
t = tv('READY');
assert.equal(t.feed({ type: 'PHASE', text: 'PLAYING' }, state(), 0), null);
t = tv('READY');
t.feed({ type: 'PHASE', text: 'SET' }, state({ state: 'SET' }), 0);
s = t.feed({ type: 'PHASE', text: 'PLAYING' }, state(), 1);
assert.deepEqual([s.kind, s.view, s.robots, s.hold_s, s.prio], ['kickoff', 'split', ['127.0.0.1|2'], 8, 2]);
t = tv('SET');
assert.equal(t.feed({ type: 'PHASE', text: 'PLAYING' }, state({ set_play_name: 'PENALTY KICK' }), 0), null);
// "first half" is a PHASE event but not a game state: lastPhase stays SET, the kick-off still counts
t = tv('SET');
assert.equal(t.feed({ type: 'PHASE', text: 'second half' }, state(), 0), null);
assert.equal(t.ctx.lastPhase, 'SET');
assert.equal(t.feed({ type: 'PHASE', text: 'PLAYING' }, state(), 0).kind, 'kickoff');
// kick-off priority 2 holds against a penalty for 8 s
assert.equal(t.feed({ type: 'PENALTY', robot: 'T19 R1', text: 'x' }, state({ penalties: { 19: { 1: ['Pick-up', 30] } } }), 7), null);
assert.ok(t.feed({ type: 'PENALTY', robot: 'T19 R1', text: 'x' }, state({ penalties: { 19: { 1: ['Pick-up', 30] } } }), 9));

// READY banner names the kicking team
t = tv('INITIAL');
assert.equal(t.feed({ type: 'PHASE', text: 'READY' }, state({ kickingTeam: 5 }), 0).banner, 'Kick-off: B-Human');

// FINISHED of the first half: "Half time"
t = tv('PLAYING');
s = t.feed({ type: 'PHASE', text: 'FINISHED' }, state({ state: 'FINISHED', score: [1, 0], first_half: true }), 0);
assert.deepEqual([s.kind, s.big.title, s.big.sub], ['finished', 'Half time', 'SPQR 1 – 0 B-Human']);
// FINISHED of the second half: "Full time" stays (no hold end) until the next PHASE event, even one that shows nothing
t = tv('PLAYING');
s = t.feed({ type: 'PHASE', text: 'FINISHED' }, state({ state: 'FINISHED', score: [2, 1], first_half: false }), 0);
assert.deepEqual([s.kind, s.big.title, s.big.sub], ['finished', 'Full time', 'SPQR 2 – 1 B-Human']);
assert.equal(t.feed({ type: 'PENALTY', robot: 'T5 R3', text: 'x' }, state({ penalties: { 5: { 3: ['Pushing', 30] } } }), 1000), null);
assert.equal(t.feed({ type: 'PHASE', text: 'second half' }, state(), 1001).kind, 'default');
// unknown team names fall back to T<n>
t = tv('PLAYING');
t.ctx.names = {};
assert.equal(t.feed({ type: 'GOAL', robot: '' }, state({ score: [1, 0] }), 0).big.title, 'GOAL · T19');
// robotName: team name when known; the last part of the IP only for two robots with the same team and number
const twins = [{ ip: '127.0.0.1', id: 3, team: 19 }, { ip: '127.0.0.2', id: 3, team: 19 }, { ip: '127.0.0.1', id: 4, team: 5 }];
assert.equal(robotName(twins[0], twins, names), 'SPQR · T19 R3\u00a0(.1)');
assert.equal(robotName(twins[1], twins, {}), 'T19 R3\u00a0(.2)');
assert.equal(robotName(twins[2], twins, names), 'B-Human · T5 R4');
assert.equal(robotName(twins[2], undefined, undefined), 'T5 R4');
assert.deepEqual(twins.map(a => robotTag(a, twins)), ['.1', '.2', '']);
// twins whose IPs end the same get the whole IP
const same = [{ ip: '10.0.0.2', id: 3, team: 19 }, { ip: '10.0.1.2', id: 3, team: 19 }];
assert.deepEqual(same.map(a => robotName(a, same, {})), ['T19 R3\u00a0(10.0.0.2)', 'T19 R3\u00a0(10.0.1.2)']);
console.log('tv_auto: all checks passed');
