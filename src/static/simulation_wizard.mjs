import {
    FIELD_PRESETS, MODELS, ROLES, circusSceneYaml, defaultScenario,
    fieldYaml, loadScenario, normalizeScenario, saveMode, saveScenario, simulationConfigYaml,
} from './simulation_config.mjs';

const $ = (id) => document.getElementById(id);
if (new URLSearchParams(location.search).get('mode') === 'settings') {
    $('wizardTitle').textContent = 'Simulation settings';
}
let scenario = loadScenario();
let step = 0;

const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
};
const input = (value, type = 'text') => {
    const node = make('input');
    node.type = type;
    node.value = value;
    if (type === 'number') node.step = 'any';
    return node;
};
const select = (value, options) => {
    const node = make('select');
    for (const [key, label] of options) {
        const option = make('option', '', label);
        option.value = key;
        node.append(option);
    }
    node.value = value;
    return node;
};
const field = (caption, control, key) => {
    const label = make('label');
    label.append(make('span', '', caption), control);
    control.dataset.field = key;
    return label;
};
const setMessage = (message, error = false) => {
    $('message').textContent = message;
    $('message').style.color = error ? '#f87171' : '#fbbf24';
};

function fillForm(s) {
    $('scenarioName').value = s.name;
    $('fieldWidth').value = s.field.width;
    $('fieldHeight').value = s.field.height;
    $('ballX').value = s.ball.x;
    $('ballY').value = s.ball.y;
    const preset = Object.entries(FIELD_PRESETS).find(([, v]) =>
        v.width === s.field.width && v.height === s.field.height);
    $('fieldPreset').value = preset?.[0] || 'custom';
    s.teams.forEach((team, index) => {
        $('team' + index + 'Number').value = team.number;
        $('team' + index + 'Name').value = team.name;
        $('team' + index + 'Color').value = team.color;
    });
    renderRosters();
}

function collectRaw() {
    const raw = {
        name: $('scenarioName').value,
        field: { width: $('fieldWidth').value, height: $('fieldHeight').value },
        ball: { x: $('ballX').value, y: $('ballY').value },
        teams: [0, 1].map((index) => ({
            number: $('team' + index + 'Number').value,
            name: $('team' + index + 'Name').value,
            color: $('team' + index + 'Color').value,
            players: [...$('roster' + index).querySelectorAll('.player-row')].map((row) => {
                const value = (key) => row.querySelector('[data-field="' + key + '"]').value;
                return {
                    number: value('number'), source: value('source'), model: value('model'),
                    role: value('role'), x: value('x'), y: value('y'), angle: value('angle'),
                };
            }),
        })),
    };
    return raw;
}

function renderRosters() {
    const root = $('rosters');
    root.replaceChildren();
    scenario.teams.forEach((team, index) => {
        const panel = make('div', 'team-card');
        const head = make('div', 'roster-head');
        head.append(make('strong', '', team.name + ' · T' + team.number));
        const add = make('button', '', 'Add player');
        add.type = 'button';
        add.addEventListener('click', () => {
            scenario = collectRaw();
            const players = scenario.teams[index].players;
            if (players.length >= 10) return setMessage('Ten players is the maximum per team.', true);
            let next = 1;
            while (players.some((player) => Number(player.number) === next)) next++;
            const side = index === 0 ? -1 : 1;
            players.push({
                number: next, source: 'ghost', model: 't1', role: 'support',
                x: side * Math.min(2 + players.length, Number(scenario.field.width) / 2 - 0.5),
                y: 0, angle: index === 0 ? 0 : Math.PI,
            });
            renderRosters();
            setMessage('');
        });
        head.append(add);
        panel.append(head);
        const rows = make('div');
        rows.id = 'roster' + index;
        team.players.forEach((player, playerIndex) => {
            const row = make('div', 'player-row');
            row.append(
                field('Number', input(player.number, 'number'), 'number'),
                field('Source', select(player.source, [['ghost', 'Ghost'], ['real', 'Real slot']]), 'source'),
                field('Model', select(player.model, MODELS.map((model) => [model, model.toUpperCase()])), 'model'),
                field('Role', select(player.role, ROLES.map((role) => [role, role])), 'role'),
                field('X (m)', input(player.x, 'number'), 'x'),
                field('Y (m)', input(player.y, 'number'), 'y'),
                field('Heading', input(player.angle, 'number'), 'angle'),
            );
            const remove = make('button', '', '×');
            remove.type = 'button';
            remove.title = 'Remove player';
            remove.setAttribute('aria-label', 'Remove player ' + player.number + ' from team ' + team.number);
            remove.addEventListener('click', () => {
                scenario = collectRaw();
                scenario.teams[index].players.splice(playerIndex, 1);
                renderRosters();
            });
            row.append(remove);
            rows.append(row);
        });
        panel.append(rows);
        root.append(panel);
    });
}

function drawPreview(s) {
    const canvas = $('preview');
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height, pad = 40;
    const scale = Math.min((W - 2 * pad) / s.field.width, (H - 2 * pad) / s.field.height);
    const w = s.field.width * scale, h = s.field.height * scale;
    const cx = W / 2, cy = H / 2;
    const point = (x, y) => [cx + x * scale, cy - y * scale];
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0e2634';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#176b46';
    ctx.fillRect(cx - w / 2, cy - h / 2, w, h);
    ctx.strokeStyle = '#d8f6e5';
    ctx.lineWidth = 2;
    ctx.strokeRect(cx - w / 2, cy - h / 2, w, h);
    ctx.beginPath();
    ctx.moveTo(cx, cy - h / 2);
    ctx.lineTo(cx, cy + h / 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, Math.min(1.5 * scale, h / 5), 0, Math.PI * 2);
    ctx.stroke();
    for (const team of s.teams) {
        for (const player of team.players) {
            const [x, y] = point(player.x, player.y);
            ctx.save();
            ctx.lineWidth = 3;
            if (player.source === 'ghost') {
                ctx.globalAlpha = 0.72;
                ctx.fillStyle = team.color;
                ctx.setLineDash([5, 4]);
            } else {
                ctx.fillStyle = '#183346';
            }
            ctx.strokeStyle = player.source === 'ghost' ? '#67e8f9' : team.color;
            ctx.beginPath();
            ctx.arc(x, y, 17, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
            ctx.restore();
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 12px system-ui';
            ctx.textAlign = 'center';
            ctx.fillText(String(player.number), x, y + 4);
            ctx.font = '11px system-ui';
            ctx.fillText(player.source === 'ghost' ? 'SIM' : 'REAL', x, y + 32);
            ctx.beginPath();
            ctx.strokeStyle = '#fff';
            ctx.moveTo(x, y);
            ctx.lineTo(x + Math.cos(player.angle) * 27, y - Math.sin(player.angle) * 27);
            ctx.stroke();
        }
    }
    const [bx, by] = point(s.ball.x, s.ball.y);
    ctx.fillStyle = '#22d3ee';
    ctx.beginPath();
    ctx.arc(bx, by, 9, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.stroke();
    ctx.fillStyle = '#e9f7ff';
    ctx.font = '13px system-ui';
    ctx.textAlign = 'left';
    ctx.fillText('Cyan ball and dashed players are simulated · click the field to move the ball', 15, H - 12);
}

function showStep(next) {
    step = Math.max(0, Math.min(3, next));
    document.querySelectorAll('[data-step]').forEach((node) => {
        node.classList.toggle('active', Number(node.dataset.step) === step);
    });
    document.querySelectorAll('[data-step-button]').forEach((button) => {
        if (Number(button.dataset.stepButton) === step) button.setAttribute('aria-current', 'step');
        else button.removeAttribute('aria-current');
    });
    $('back').disabled = step === 0;
    $('next').hidden = step === 3;
    if (step === 3) {
        drawPreview(scenario);
        const ghosts = scenario.teams.reduce((count, team) =>
            count + team.players.filter((player) => player.source === 'ghost').length, 0);
        const real = scenario.teams.reduce((count, team) =>
            count + team.players.filter((player) => player.source === 'real').length, 0);
        $('summary').textContent = scenario.name + ' · ' + scenario.field.width + ' × ' +
            scenario.field.height + ' m · ' + real + ' real slot(s), ' + ghosts + ' ghost(s)\n' +
            scenario.teams.map((team) => team.name + ' (T' + team.number + '): ' +
                team.players.map((player) => 'R' + player.number + ' ' + player.model.toUpperCase() +
                    ' ' + player.source).join(', ')).join('\n');
    }
    setMessage('');
}

function accept() {
    try {
        scenario = normalizeScenario(collectRaw());
        return true;
    } catch (error) {
        setMessage(error.message, true);
        return false;
    }
}

function download(filename, content, mime) {
    const url = URL.createObjectURL(new Blob([content], { type: mime }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('fieldPreset').addEventListener('change', () => {
    const preset = FIELD_PRESETS[$('fieldPreset').value];
    if (preset) {
        $('fieldWidth').value = preset.width;
        $('fieldHeight').value = preset.height;
    }
});
for (const id of ['fieldWidth', 'fieldHeight']) {
    $(id).addEventListener('input', () => {
        const preset = Object.entries(FIELD_PRESETS).find(([, value]) =>
            Number($('fieldWidth').value) === value.width && Number($('fieldHeight').value) === value.height);
        $('fieldPreset').value = preset?.[0] || 'custom';
    });
}
$('back').addEventListener('click', () => showStep(step - 1));
$('next').addEventListener('click', () => { if (accept()) showStep(step + 1); });
document.querySelectorAll('[data-step-button]').forEach((button) => button.addEventListener('click', () => {
    const target = Number(button.dataset.stepButton);
    if (target <= step || accept()) showStep(target);
}));
$('saveScenario').addEventListener('click', () => {
    if (!accept()) return;
    saveScenario(scenario);
    setMessage('Scenario saved in this browser. Open the hybrid field to overlay its ghosts.');
});
$('openHybrid').addEventListener('click', (event) => {
    if (!accept()) return event.preventDefault();
    saveScenario(scenario);
    saveMode('hybrid');
});
$('downloadJson').addEventListener('click', () => {
    if (accept()) download('oraculum-scenario.json', JSON.stringify(scenario, null, 2) + '\n', 'application/json');
});
$('downloadScene').addEventListener('click', () => {
    if (accept()) download('oraculum-circus-scene.yaml', circusSceneYaml(scenario), 'text/yaml');
});
$('downloadField').addEventListener('click', () => {
    if (accept()) download('oraculum_custom.yaml', fieldYaml(scenario), 'text/yaml');
});
$('downloadSimConfig').addEventListener('click', () => {
    if (accept()) download('oraculum_custom-simulation.yaml', simulationConfigYaml(scenario), 'text/yaml');
});
$('preview').addEventListener('click', (event) => {
    if (step !== 3) return;
    const rect = $('preview').getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * $('preview').width;
    const y = (event.clientY - rect.top) / rect.height * $('preview').height;
    const scale = Math.min(($('preview').width - 80) / scenario.field.width,
        ($('preview').height - 80) / scenario.field.height);
    const bx = Math.max(-scenario.field.width / 2, Math.min(scenario.field.width / 2, (x - $('preview').width / 2) / scale));
    const by = Math.max(-scenario.field.height / 2, Math.min(scenario.field.height / 2, - (y - $('preview').height / 2) / scale));
    $('ballX').value = scenario.ball.x = Math.round(bx * 10) / 10;
    $('ballY').value = scenario.ball.y = Math.round(by * 10) / 10;
    drawPreview(scenario);
    setMessage('Ball moved. Save the scenario to use this position on the live field.');
});

fillForm(scenario || defaultScenario());
showStep(0);

// Launch remains explicit and independent of saving a browser preview.
import { mountOperationWorkflows } from "./operation_workflows.mjs";
mountOperationWorkflows(document.getElementById("simulationWorkflow"), {scenario:()=>accept()?scenario:null});
