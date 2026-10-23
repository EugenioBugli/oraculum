// Self-check of the match helpers in src/static/field_model.js: budgetSummary, stateMismatch, gcSummary kick-off,
// teamLegend, teamPrimary, teamSummary (link stale), robotTexts, isRobot, robotName (twins), robotTag, linkStale, shortName, dampWord. Run: node tools/check_field_model.mjs   (exit 0 = pass)
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync(new URL('../src/static/field_model.js', import.meta.url), 'utf8');
const { budgetSummary, stateMismatch, gcSummary, teamLegend, teamPrimary, teamSummary, robotTexts, isRobot, robotName, robotTag, linkStale, shortName, dampWord } = await import('data:text/javascript,' + encodeURIComponent(src));

const gc = { state: 'SET', teams: [5, 19], own_team_index: 1, message_budget: [12000, 9000], kickingTeam: 19,
             penalties: { 19: { 3: ['Pushing', 20] } } };
assert.deepEqual([budgetSummary(gc).text, budgetSummary(gc).used], ['9,000 messages left', 25]);
assert.match(budgetSummary({}).text, /no GameController/);
assert.match(budgetSummary({ ...gc, own_team_index: -1 }).text, /not in this game/);
assert.equal(stateMismatch({ team: 19, id: 3, state: 'R' }, gc), 'robot: not penalised');
assert.match(stateMismatch({ team: 19, id: 3, state: 'R' }, gc, true), /does not know/);
assert.equal(stateMismatch({ team: 19, id: 3, state: 'P' }, gc), '');
assert.equal(stateMismatch({ team: 19, id: 2, state: 'P' }, gc), 'GC: not penalised');
assert.match(stateMismatch({ team: 7, id: 2, state: 'R' }, gc), /T7 is not/);
assert.equal(stateMismatch({ team: 7, id: 2, state: 'P' }, {}), '');  // no GameController: nothing to compare
assert.match(gcSummary(gc).detail, /kick-off T19/);
assert.doesNotMatch(gcSummary({ ...gc, state: 'PLAYING' }).detail, /kick-off/);
assert.equal(teamLegend([{ team: 5, color: 'red' }, { team: 19, color: 'blue' }, { team: 5, color: 'red' }]).split('T5').length, 2);
const fake = [{ team: 5, id: 4, color: '#ffffff' }, { team: 5, id: 2, color: '#006778' }, { team: 19, id: 3, color: '#000000' }, { team: 19, id: 1, color: '#822433' }];
assert.deepEqual([...teamPrimary(fake)].sort(), [[19, '#822433'], [5, '#006778']]);  // white, black, grey are never primary
assert.ok(teamLegend(fake).indexOf('rgb(20,123,140)') < teamLegend(fake).indexOf('rgb(255,255,255)'));  // primary dot first
assert.match(teamSummary({ agents: fake.map(a => ({ ...a, ip: '10.0.0.1' })), fleet: { link: { '10.0.0.1': { age: 1.2 } } } }, new Map()), /4 links stale/);
assert.doesNotMatch(teamSummary({ agents: fake, fleet: { link: {} } }, new Map()), /stale/);
assert.match(teamSummary({ agents: fake.map(a => ({ ...a, ip: '10.0.0.1' })), fleet: { link: { '10.0.0.1': { age: 1.2 } } } }, new Map()), /^0\/4 live/);  // a stale robot is not live
assert.match(teamSummary({ agents: fake, fleet: { link: {} } }, new Map()), /^4\/4 live/);
const twins = [{ team: 19, id: 3, ip: '127.0.0.1' }, { team: 19, id: 3, ip: '127.0.0.2' }, { team: 5, id: 3, ip: '127.0.0.1' }];
assert.deepEqual(twins.map(a => robotName(a, twins)), ['T19 R3 ·.1', 'T19 R3 ·.2', 'T5 R3']);
assert.equal(new Set(twins.map(a => robotName(a, twins))).size, 3);  // never the same text twice
assert.deepEqual(['T19 R3', 'T19 R3'], twins.slice(0, 2).map(robotName));  // .map(robotName): the index is not a list
const sameEnd = [{ team: 19, id: 3, ip: '10.0.1.7' }, { team: 19, id: 3, ip: '10.0.2.7' }];
assert.deepEqual(sameEnd.map(a => robotName(a, sameEnd)), ['T19 R3 ·10.0.1.7', 'T19 R3 ·10.0.2.7']);
assert.deepEqual(twins.map(a => robotTag(a, twins)), ['.1', '.2', '']);
const three = [1, 2, 3].map(n => ({ team: 19, id: 3, ip: `127.0.0.${n}` }));  // each twin unlocks DAMP with its own word
assert.deepEqual(three.map(a => dampWord(robotName(a, three))), ['R3.1', 'R3.2', 'R3.3']);
assert.deepEqual(three.map(a => shortName(robotName(a, three))), ['T19 R3·.1', 'T19 R3·.2', 'T19 R3·.3']);
assert.deepEqual(sameEnd.map(a => dampWord(robotName(a, sameEnd))), ['R3.10.0.1.7', 'R3.10.0.2.7']);  // last octets match: whole IP
// a twin that went silent (not in the agents list any more) keeps the suffix of the live one for 60 s
const pair = [{ team: 7, id: 4, ip: '127.0.0.5' }, { team: 7, id: 4, ip: '127.0.0.6' }];
pair.forEach(a => robotName(a, pair));
assert.equal(robotName(pair[0], [pair[0]]), 'T7 R4 ·.5');
assert.equal(dampWord('T19 R3'), 'R3');
assert.equal(shortName('T5 R12'), 'T5 R12');
assert.equal(shortName('', '10.0.0.9'), '10.0.0.9');
assert.equal(dampWord('', '10.0.0.9'), '10.0.0.9');
assert.ok(linkStale({ fleet: { link: { '1.1.1.1': { age: 1 } } } }, { ip: '1.1.1.1' }) && !linkStale({}, { ip: '1.1.1.1' }));
const texts = [{ agent_id: 3, ip: '10.0.0.1', path: 'a' }, { agent_id: 3, ip: '10.0.0.2', path: 'b' }, { agent_id: 3, path: 'c' }];
assert.equal(robotTexts(texts, 3, '10.0.0.1').map(t => t.path).join(), 'a,c');
assert.ok(isRobot({ id: 0 }, 0, '127.0.0.1') && !isRobot({ id: 3, ip: '10.0.0.2' }, 3, '10.0.0.1'));
console.log('field_model: all checks passed');
