// AUTO shots of the public TV view (src/tv.html): which view the TV shows after a game event.
// Pure functions with no DOM and no imports, so tools/check_tv_auto.mjs can test them in node.
// A shot: {kind, view: field|camera|split, robots: ["ip|id"], banner, big, banner_s, delay_s, hold_s, prio}.
//   banner: one-line text, or "" (none); big: {title, sub} for the GOAL and "Half time" / "Full time" cards, else null.
//   banner_s: seconds the banner shows; delay_s: seconds of field before the camera; hold_s: length of the shot.
// Only the event types GOAL, PENALTY, PHASE and SETPLAY count. The TV never shows the text of an event.

const GAME_STATES = ['INITIAL', 'READY', 'SET', 'PLAYING', 'FINISHED'];
export const DEFAULT_SHOT = { kind: 'default', view: 'field', robots: [], banner: '', big: null, banner_s: 0, delay_s: 0, hold_s: 0, prio: 0 };

export const teamName = (n, names) => (names && names[String(n)]) || `T${n ?? '?'}`;
// Robot label of the TV and the director: "T19 R3", with the team name "SPQR · T19 R3". Two robots with the same team
// and number (two IPs) get the last part of their IP: "T19 R3 (.1)" and "T19 R3 (.2)", so no two robots read the same.
// A no-break space keeps "(.2)" on the line of "R3". (The operator pages use field_model.js robotName, not this one.)
export function robotName(agent, agents, names) {
    const team = names && names[String(agent.team)], tag = robotTag(agent, agents);
    return `${team ? team + ' · ' : ''}T${agent.team ?? '?'} R${agent.id}${tag ? `\u00a0(${tag})` : ''}`;
}
// ".1" (last part of the IP) when another robot has the same team and number, else "": the tag under a 2D disc.
// Twins whose IPs end the same (10.0.0.2 and 10.0.1.2) get the whole IP.
export function robotTag(agent, agents) {
    const last = ip => String(ip).split('.').pop();
    const twins = (agents || []).filter(b => b.ip !== agent.ip && b.team === agent.team && b.id === agent.id);
    if (!twins.length) return '';
    return twins.some(b => last(b.ip) === last(agent.ip)) ? String(agent.ip) : '.' + last(agent.ip);
}
const words = s => { s = String(s || '').toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
const shot = (fields) => ({ ...DEFAULT_SHOT, ...fields });

// Team number whose score rose since prevScore, or null.
export function goalTeam(prevScore, score, teams) {
    for (const i of [0, 1]) {
        if ((score?.[i] ?? 0) > (prevScore?.[i] ?? 0)) return teams?.[i] ?? null;
    }
    return null;
}

// "ip|id" of that team's robot nearest to the team ball (no ball: the lowest number), or "".
// GC player = the agent with agent.team == GC team number and agent.id == player number.
export function nearestRobot(teamNumber, state) {
    const ball = state?.ball, ok = v => Number.isFinite(v);
    const mine = (state?.agents || []).filter(a => a.team === teamNumber && ok(a.x) && ok(a.y));
    if (!mine.length) return '';
    const d = a => ball && ok(ball.x) && ok(ball.y) ? Math.hypot(a.x - ball.x, a.y - ball.y) : a.id;
    const best = mine.reduce((p, a) => (d(a) < d(p) ? a : p));
    return `${best.ip}|${best.id}`;
}

// The shot for one event, or null when the event does not change the TV.
// ctx = {scoreSeen, lastPhase, current: {prio, until, kind}, now (s), names}. Updates ctx.scoreSeen (GOAL) and
// ctx.lastPhase (PHASE events that name a game state). The caller makes the returned shot current until now + hold_s.
export function nextShot(ev, state, ctx) {
    const gc = state?.gamecontroller || {}, name = n => teamName(n, ctx.names);
    let s = null;
    if (ev.type === 'GOAL') {
        // The GOAL event names no robot: the team comes from the score change, never from the event text.
        const team = goalTeam(ctx.scoreSeen, gc.score, gc.teams);
        ctx.scoreSeen = (gc.score || []).slice();
        if (team === null) return null;
        const [t0, t1] = gc.teams || [], [s0, s1] = gc.score || [0, 0];
        // ponytail: the scorer is a guess, the robot of that team nearest to the ball now; use a real scorer when the GC sends one.
        const robot = nearestRobot(team, state);
        s = shot({ kind: 'goal', view: robot ? 'camera' : 'field', robots: robot ? [robot] : [], banner_s: robot ? 3 : 10,
                   big: { title: `GOAL · ${name(team)}`, sub: `${name(t0)} ${s0} – ${s1} ${name(t1)}` }, delay_s: 3, hold_s: 10, prio: 3 });
    } else if (ev.type === 'PHASE') {
        const phase = String(ev.text || '');
        if (!GAME_STATES.includes(phase)) {
            s = null;  // "first half" / "second half": not a game state, lastPhase stays
        } else {
            const prev = ctx.lastPhase;
            ctx.lastPhase = phase;
            if (phase === 'PLAYING' && prev === 'SET' && !gc.set_play_name) {  // kick-off
                const robot = nearestRobot(gc.kickingTeam, state);
                if (robot) s = shot({ kind: 'kickoff', view: 'split', robots: [robot], hold_s: 8, prio: 2 });
            } else if (phase === 'READY') {
                s = shot({ kind: 'ready', banner: `Kick-off: ${name(gc.kickingTeam)}`, banner_s: 5, hold_s: 5, prio: 1 });
            } else if (phase === 'FINISHED') {
                const [t0, t1] = gc.teams || [], [s0, s1] = gc.score || [0, 0];
                // FINISHED ends each half: the GameController's first_half says which one
                s = shot({ kind: 'finished', big: { title: gc.first_half === false ? 'Full time' : 'Half time', sub: `${name(t0)} ${s0} – ${s1} ${name(t1)}` },
                           banner_s: Infinity, hold_s: Infinity, prio: 1 });
            }
        }
        // The "Half time" / "Full time" card stays until the next PHASE event, whatever that event shows.
        if (!s && ctx.current?.kind === 'finished') s = shot({});
        if (s && ctx.current?.kind === 'finished') return s;
    } else if (ev.type === 'PENALTY') {
        const m = /^T(\d+) R(\d+)$/.exec(ev.robot || '');
        if (!m || /back in play$/.test(ev.text || '')) return null;
        const pen = gc.penalties?.[m[1]]?.[m[2]]?.[0];
        if (!pen) return null;  // already back in play: nothing to show
        s = shot({ kind: 'penalty', banner: `${name(+m[1])} #${m[2]}: ${pen}`, banner_s: 5, hold_s: 5, prio: 1 });
    } else if (ev.type === 'SETPLAY') {
        if (!gc.set_play_name) return null;
        s = shot({ kind: 'setplay', banner: `${words(gc.set_play_name)} · ${name(gc.kickingTeam)}`, banner_s: 5, hold_s: 5, prio: 1 });
    }
    if (!s) return null;
    const cur = ctx.current;
    if (cur?.kind === 'finished') return null;  // only a PHASE event (above) ends "Half time" / "Full time"
    if (cur && s.prio < cur.prio && ctx.now < cur.until) return null;  // a stronger shot is still running
    return s;
}
