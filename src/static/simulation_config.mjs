// Browser-local scenario for display-only ghosts. No packet is sent to a robot.
export const SCENARIO_KEY = 'oraculum_scenario_v1';
export const MODE_KEY = 'oraculum_source_mode_v1';
export const MODELS = ['t1', 't2', 'k1'];
export const ROLES = ['goalie', 'striker', 'defender', 'support'];
export const FIELD_PRESETS = {
    adult: { label: 'Adult 14 × 9 m', width: 14, height: 9 },
    spl: { label: 'SPL 9 × 6 m', width: 9, height: 6 },
    rcap: { label: 'RCAP 22 × 14 m', width: 22, height: 14 },
};

export function defaultScenario() {
    return {
        name: 'Robot 6 versus a ghost',
        field: { width: 14, height: 9 },
        ball: { x: 0, y: 0 },
        teams: [
            { number: 19, name: 'SPQR', color: '#b83232', players: [
                { number: 6, source: 'real', model: 't1', role: 'striker', x: -2, y: 0, angle: 0 },
            ] },
            { number: 2, name: 'Ghosts', color: '#2385d1', players: [
                { number: 1, source: 'ghost', model: 't1', role: 'striker', x: 2, y: 0, angle: Math.PI },
            ] },
        ],
    };
}

const number = (value, label, min, max) => {
    const n = Number(value);
    if (!Number.isFinite(n) || n < min || n > max) throw new Error(label + ' must be between ' + min + ' and ' + max + '.');
    return n;
};
const integer = (value, label, min, max) => {
    const n = number(value, label, min, max);
    if (!Number.isInteger(n)) throw new Error(label + ' must be an integer.');
    return n;
};

export function normalizeScenario(input) {
    if (!input || typeof input !== 'object') throw new Error('Scenario is missing.');
    const width = number(input.field?.width, 'Field length', 6, 30);
    const height = number(input.field?.height, 'Field width', 4, 20);
    if (width <= height) throw new Error('Field length must exceed field width.');
    const teams = input.teams;
    if (!Array.isArray(teams) || teams.length !== 2) throw new Error('Choose two teams.');
    const normalized = {
        name: String(input.name || 'Custom scenario').trim().slice(0, 64),
        field: { width, height },
        ball: {
            x: number(input.ball?.x, 'Ball X', -width / 2, width / 2),
            y: number(input.ball?.y, 'Ball Y', -height / 2, height / 2),
        },
        teams: teams.map((team, teamIndex) => {
            const teamNumber = integer(team.number, 'Team number', 1, 99);
            const color = String(team.color || '').trim();
            if (!/^#[0-9a-fA-F]{6}$/.test(color)) throw new Error('Team color must be a six-digit hex color.');
            if (!Array.isArray(team.players) || team.players.length > 10) throw new Error('A team can have at most ten players.');
            const seen = new Set();
            const players = team.players.map((player) => {
                const id = integer(player.number, 'Player number', 1, 20);
                if (seen.has(id)) throw new Error('Player numbers must be unique within team ' + teamNumber + '.');
                seen.add(id);
                const source = String(player.source);
                const model = String(player.model);
                const role = String(player.role);
                if (!['real', 'ghost'].includes(source)) throw new Error('Player source must be real or ghost.');
                if (!MODELS.includes(model)) throw new Error('Unknown robot model.');
                if (!ROLES.includes(role)) throw new Error('Unknown player role.');
                return {
                    number: id, source, model, role,
                    x: number(player.x, 'Player X', -width / 2, width / 2),
                    y: number(player.y, 'Player Y', -height / 2, height / 2),
                    angle: number(player.angle, 'Heading', -Math.PI * 2, Math.PI * 2),
                };
            });
            return { number: teamNumber, name: String(team.name || 'Team ' + (teamIndex + 1)).trim().slice(0, 32), color, players };
        }),
    };
    if (normalized.teams[0].number === normalized.teams[1].number) throw new Error('The two teams need different numbers.');
    if (!normalized.teams.some((team) => team.players.some((player) => player.source === 'ghost'))) {
        throw new Error('Add at least one simulated player.');
    }
    return normalized;
}

export function loadScenario() {
    try {
        const saved = localStorage.getItem(SCENARIO_KEY);
        return saved ? normalizeScenario(JSON.parse(saved)) : defaultScenario();
    } catch {
        return defaultScenario();
    }
}

export function saveScenario(input) {
    const scenario = normalizeScenario(input);
    localStorage.setItem(SCENARIO_KEY, JSON.stringify(scenario));
    return scenario;
}

export function loadMode() {
    try {
        const query = new URLSearchParams(location.search).get('source');
        if (query === 'real' || query === 'hybrid') return query;
        return localStorage.getItem(MODE_KEY) === 'hybrid' ? 'hybrid' : 'real';
    } catch {
        return 'real';
    }
}

export function saveMode(mode) {
    if (!['real', 'hybrid'].includes(mode)) throw new Error('Unknown source mode.');
    localStorage.setItem(MODE_KEY, mode);
    return mode;
}

// Preserve the gateway's command state. Ghost addresses cannot be command targets and every ghost is read-only.
export function overlayState(live, scenario, displayField) {
    const config = normalizeScenario(scenario);
    const sx = (displayField?.width || config.field.width) / config.field.width;
    const sy = (displayField?.height || config.field.height) / config.field.height;
    const real = live?.agents || [];
    const occupied = new Set(real.map((a) => String(a.team) + '|' + String(a.id)));
    const ghosts = config.teams.flatMap((team) => team.players
        .filter((player) => player.source === 'ghost' && !occupied.has(String(team.number) + '|' + String(player.number)))
        .map((player) => ({
            id: player.number, team: team.number, x: player.x * sx, y: player.y * sy,
            angle: player.angle, role: player.role, state: 'Preview', color: team.color,
            ip: 'sim.' + team.number + '.' + player.number, robot: player.model,
            battery: -1, fallen: false, readonly: true, simulated: true,
            sources: ['sim'], source_age: { sim: 0 }, sys: { link: 'none' },
        })));
    const link = { ...(live?.fleet?.link || {}) };
    for (const ghost of ghosts) link[ghost.ip] = { age: 0, hz: 0 };
    const drawings = [...(live?.drawings || [])];
    if (live?.ball) drawings.push({
        type: 'circle', path: 'real/ball', frame: 'field',
        coords: [live.ball.x, live.ball.y], size: 0.14, color: [255, 127, 0],
    });
    return {
        ...live, agents: [...real, ...ghosts],
        ball: { x: config.ball.x * sx, y: config.ball.y * sy, simulated: true },
        real_ball: live?.ball || null,
        drawings,
        fleet: { ...(live?.fleet || {}), link },
        hybrid: { mode: 'hybrid', name: config.name, ghosts: ghosts.length, scaled: sx !== 1 || sy !== 1 },
    };
}

export function circusSceneYaml(input) {
    const s = normalizeScenario(input);
    const model = { t1: 'Booster-T1', t2: 'Booster-T2', k1: 'Booster-K1' };
    const height = { t1: 0.68, t2: 0.98, k1: 0.53 };
    const lines = [
        '# Generated by the Oraculum scenario wizard. Ghost players only.',
        '# Install oraculum_custom.yaml into Circus simulation_configs and fields resources before launching.',
        '# Circus currently starts its ball at field centre; the wizard ball position is UI preview only.',
        'simulation_config: oraculum_custom',
        'teams:',
    ];
    for (const [index, team] of s.teams.entries()) {
        const players = team.players.filter((player) => player.source === 'ghost');
        if (!players.length) continue;
        lines.push('  ' + (index === 0 ? 'red' : 'blue') + ':');
        lines.push('    number: ' + team.number);
        lines.push('    players:');
        for (const player of players) {
            lines.push('      - type: ' + model[player.model]);
            lines.push('        number: ' + player.number);
            // Circus uses "goalkeeper"; "support" is a display role and has no scene role.
            if (player.role !== 'support') lines.push('        role: ' + (player.role === 'goalie' ? 'goalkeeper' : player.role));
            lines.push('        position: [' + player.x + ', ' + player.y + ', ' + height[player.model] + ']');
            lines.push('        orientation: [0, 0, ' + player.angle + ']');
        }
    }
    return lines.join('\n') + '\n';
}

export function fieldYaml(input) {
    const s = normalizeScenario(input);
    const x = s.field.width / 14, y = s.field.height / 9, k = Math.min(x, y);
    const entries = {
        width: s.field.width, height: s.field.height,
        center_radius: +(1.5 * k).toFixed(3),
        goal_area_width: +(1 * x).toFixed(3), goal_area_height: +(4 * y).toFixed(3),
        penalty_area_width: +(3 * x).toFixed(3), penalty_area_height: +(6.5 * y).toFixed(3),
        penalty_mark_distance: +(2.1 * x).toFixed(3),
        goal_width: +(2.6 * y).toFixed(3), goal_height: 1.8, goal_depth: 0.6,
        line_width: 0.08, ball_radius: 0.11,
    };
    return Object.entries(entries).map(([key, value]) => key + ': ' + value).join('\n') + '\n';
}

export function simulationConfigYaml(input) {
    normalizeScenario(input);
    return 'simulation:\n  max_simulation_time: -1\ngame:\n  field: oraculum_custom\n'
        + '  game_state_logging: true\n  game_duration: 600\n  automatic_restart: true\n';
}
