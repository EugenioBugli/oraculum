// Pure offline checks: scenario round-trip, export boundaries and ghost motion.
import assert from 'node:assert/strict';
import { defaultScenario, normalizeScenario, overlayState, circusSceneYaml, fieldYaml,
    simulationConfigYaml } from '../src/static/simulation_config.mjs';
import { advanceGhostPose } from '../src/static/hybrid_overlay.mjs';

const scenario = defaultScenario();
scenario.field = {width:18, height:12};
scenario.ball = {x:1, y:-2};
scenario.teams[1].players.push({number:2,source:'ghost',model:'k1',role:'goalie',x:3,y:1,angle:0});
assert.deepEqual(normalizeScenario(JSON.parse(JSON.stringify(scenario))), scenario);
const bad = structuredClone(scenario);
bad.teams[1].players[1].number = 1;
assert.throws(() => normalizeScenario(bad), /unique/);
bad.teams[1].players[1].number = 2;
bad.ball.x = 20;
assert.throws(() => normalizeScenario(bad), /Ball X/);

const real = {id:6,team:19,ip:'192.0.2.6',x:1,y:2,angle:0,latch:'stop'};
const live = {agents:[real],ball:{x:2,y:3},lock:{you:true},match:true,fleet:{link:{[real.ip]:{age:2}}}};
const before = structuredClone(live);
const mixed = overlayState(live,scenario,{width:18,height:12});
assert.deepEqual(live,before,'overlay must not mutate live telemetry');
assert.equal(mixed.agents[0],real,'real pose/latch identity preserved');
assert.equal(mixed.lock,live.lock);
assert.equal(mixed.match,true);
assert.equal(mixed.agents.filter(a=>a.simulated).length,2);
assert(mixed.agents.filter(a=>a.simulated).every(a=>a.readonly && a.ip.startsWith('sim.')));
const collision = overlayState({...live,agents:[real,{id:1,team:2,ip:'192.0.2.1'}]},scenario);
assert.equal(collision.agents.filter(a=>a.simulated).length,1,'real robot takes precedence over ghost slot');

const scene = circusSceneYaml(scenario);
assert(!scene.includes('number: 6'),'real slot never exported as a simulated robot');
assert(scene.includes('type: Booster-K1') && scene.includes('role: goalkeeper'));
assert(scene.includes('ball at field centre'),'export explains ball limitation');
assert(fieldYaml(scenario).includes('width: 18\nheight: 12'));
assert(simulationConfigYaml(scenario).includes('field: oraculum_custom'));
const field={width:14,height:9}, origin={x:0,y:0,angle:0};
const forward=advanceGhostPose(origin,{vx:1},1,field);
const backward=advanceGhostPose(origin,{vx:-1},1,field);
assert(forward.x>0 && backward.x<0 && forward.y===0);
assert(advanceGhostPose(origin,{vy:1},1,field).y>0);
assert(advanceGhostPose({...origin,angle:Math.PI/2},{vx:1},1,field).y>0);
assert(advanceGhostPose(origin,{vtheta:1},1,field).angle>0);
assert.deepEqual(advanceGhostPose(origin,{},1,field),origin,'released stick stays still');
const edge=advanceGhostPose({x:6.84,y:0,angle:0},{vx:100},10,field);
assert(edge.x<=6.85,'preview stays inside field');
console.log('simulation: round-trip, validation, export isolation and ghost kinematics passed');
