"""Figure setup, animation loop, and entry point."""

import os
import sys

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from .config import load_config, load_teams
from .field import draw_field
from matplotlib.patches import Circle, FancyBboxPatch
from .agents import create_agents, make_agent_artists, update_agent_artists, Ball, draw_agent_legend
from .socket_client import UDPReceiver
from .gc_client import GCReceiver


_ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")

_SET_PLAY_NAMES = {
    1: "DIRECT FREE KICK",
    2: "INDIRECT FREE KICK",
    3: "PENALTY KICK",
    4: "THROW IN",
    5: "GOAL KICK",
    6: "CORNER KICK",
}

# Column boundaries in axes-fraction coordinates (x=0..1 above the field axes)
_SEP_XS      = [0.17, 0.27, 0.42, 0.63]
_COL_CENTERS = [0.085, 0.22, 0.345, 0.525]   # STATE  HALF  TIME  EVENT
_COL_LABELS  = ["STATE", "HALF", "TIME", "EVENT"]
# SCORE column (0.63–1.0): left-team | numbers | right-team
_SCORE_X_L   = 0.695   # right-aligned team name
_SCORE_X_MID = 0.815   # centered score numbers
_SCORE_X_R   = 0.935   # left-aligned team name
# Panel vertical coordinates (in axes fraction, above y=1.0)
_Y_BOT, _Y_MID, _Y_TOP = 1.005, 1.055, 1.095
_Y_HDR = (_Y_MID + _Y_TOP) / 2   # header label row
_Y_VAL = (_Y_BOT + _Y_MID) / 2   # value row


def _visible_color(css: str) -> str:
    """Ensure a CSS color name is legible on a dark background."""
    return "#888888" if css.lower() in ("black", "#000", "#000000") else css


def _make_gc_artists(ax):
    """Build the static GC info panel above the field axes and return mutable text artists."""
    tr = ax.transAxes
    z  = dict(zorder=7)

    # Dark background panel
    ax.add_patch(FancyBboxPatch(
        (0.0, _Y_BOT), 1.0, _Y_TOP - _Y_BOT,
        boxstyle="square,pad=0", facecolor="#252525", edgecolor="none",
        transform=tr, clip_on=False, zorder=5,
    ))

    # Border and separator lines
    lkw = dict(transform=tr, clip_on=False, color="#555555", linewidth=0.8, zorder=6)
    for x in _SEP_XS:
        ax.plot([x, x], [_Y_BOT, _Y_TOP], **lkw)
    for y in (_Y_BOT, _Y_MID, _Y_TOP):
        ax.plot([0.0, 1.0], [y, y], **lkw)

    # Column header labels (static)
    hkw = dict(transform=tr, clip_on=False, ha="center", va="center",
               fontfamily="monospace", color="#666666", fontsize=8,
               fontweight="bold", **z)
    for label, x in zip(_COL_LABELS, _COL_CENTERS):
        ax.text(x, _Y_HDR, label, **hkw)
    ax.text(_SCORE_X_MID, _Y_HDR, "SCORE", **hkw)

    # Mutable value texts
    vkw = dict(transform=tr, clip_on=False, ha="center", va="center",
               fontfamily="monospace", color="#dddddd", fontsize=10, **z)
    state_t = ax.text(_COL_CENTERS[0], _Y_VAL, "INITIAL", **vkw)
    half_t  = ax.text(_COL_CENTERS[1], _Y_VAL, "\u2014",  **vkw)
    time_t  = ax.text(_COL_CENTERS[2], _Y_VAL, "\u2014",  **vkw)
    event_t = ax.text(_COL_CENTERS[3], _Y_VAL, "",         **vkw)

    skw = dict(transform=tr, clip_on=False, va="center",
               fontfamily="monospace", fontsize=8, **z)
    team0_t = ax.text(_SCORE_X_L,   _Y_VAL, "", color="#dddddd", ha="right",  **skw)
    nums_t  = ax.text(_SCORE_X_MID, _Y_VAL, "\u2014", color="#dddddd", ha="center", **skw)
    team1_t = ax.text(_SCORE_X_R,   _Y_VAL, "", color="#dddddd", ha="left",   **skw)

    return state_t, half_t, time_t, event_t, team0_t, nums_t, team1_t


def _update_gc_artists(artists, gc, teams_map: dict) -> None:
    state_t, half_t, time_t, event_t, team0_t, nums_t, team1_t = artists

    half = "1st" if gc.first_half else "2nd"
    mins, secs = divmod(max(gc.secs_remaining, 0), 60)

    if gc.set_play != 0:
        event = _SET_PLAY_NAMES.get(gc.set_play, str(gc.set_play))
    elif gc.game_phase != 0:
        event = gc.phase_name
    else:
        event = ""

    state_t.set_text(gc.state_name)
    half_t.set_text(half)
    time_t.set_text(f"{mins:02d}:{secs:02d}")
    event_t.set_text(event)

    if len(gc.teams) == 2:
        t0, t1 = gc.teams[0], gc.teams[1]
        info0 = teams_map.get(t0.team_number, {})
        info1 = teams_map.get(t1.team_number, {})
        n0 = info0.get("name", str(t0.team_number))[:13]
        n1 = info1.get("name", str(t1.team_number))[:13]
        cols0 = info0.get("colors", [])
        cols1 = info1.get("colors", [])
        c0 = _visible_color(cols0[t0.field_player_colour]) if t0.field_player_colour < len(cols0) else "#dddddd"
        c1 = _visible_color(cols1[t1.field_player_colour]) if t1.field_player_colour < len(cols1) else "#dddddd"
        team0_t.set_text(n0);  team0_t.set_color(c0)
        nums_t.set_text(f"{t0.score}  \u2014  {t1.score}")
        team1_t.set_text(n1);  team1_t.set_color(c1)


def main() -> None:
    root = os.path.abspath(_ROOT_DIR)

    try:
        cfg, field, field_name = load_config(root)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    teams_map = load_teams(root)

    disp = cfg.get("display", {})
    title = disp.get("title", "Field Viewer")

    W = field["width"]
    H = field["height"]
    hw, hh = W / 2, H / 2
    margin = max(W, H) * 0.06

    # --- Figure setup ---
    fig_w = 10
    fig_h_field = fig_w * (H + 2 * margin) / (W + 2 * margin)
    legend_h = 0.75  # inches
    fig, (ax, ax_leg) = plt.subplots(
        2, 1,
        figsize=(fig_w, fig_h_field + legend_h),
        gridspec_kw={"height_ratios": [fig_h_field, legend_h], "hspace": 0.0},
    )
    fig.patch.set_facecolor("#1e1e1e")
    fig.canvas.manager.set_window_title(title)
    fig.canvas.manager.window.setMinimumSize(int(fig_w * fig.dpi), int((fig_h_field + legend_h) * fig.dpi))

    draw_field(ax, field, cfg)

    ax.set_xlim(-hw - margin, hw + margin)
    ax.set_ylim(-hh - margin, hh + margin)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.suptitle(title,
                 color="#822433", fontsize=22, fontweight="bold",
                 fontfamily="serif")
    gc_artists = _make_gc_artists(ax)

    # --- Socket receiver (optional) ---
    sock_cfg = cfg.get("socket", {})
    receiver: UDPReceiver | None = None
    if sock_cfg.get("enabled", False):
        receiver = UDPReceiver(
            host=sock_cfg.get("host", "0.0.0.0"),
            port=sock_cfg.get("port", 10006),
        )
        receiver.start()

    # --- GameController receiver (optional) ---
    gc_cfg = cfg.get("game_controller", {})
    gc_receiver: GCReceiver | None = None
    if gc_cfg.get("enabled", False):
        own_team = gc_cfg.get("own_team") or None
        gc_receiver = GCReceiver(
            host=gc_cfg.get("host", "0.0.0.0"),
            port=gc_cfg.get("port", 3838),
            own_team=own_team,
        )
        gc_receiver.start()

    # --- Agents ---
    n_agents = cfg.get("agents", {}).get("count", 5)
    speed = cfg.get("agents", {}).get("speed", 1.5)
    agents = create_agents(n_agents, hw, hh, speed=speed)

    agent_size = min(W, H) * 0.032  # radius of the agent circle

    agent_artists: list[tuple] = []
    for i, agent in enumerate(agents):
        agent_artists.append(make_agent_artists(ax, agent, i, agent_size))

    # --- Legend ---
    draw_agent_legend(ax_leg, agents)

    # --- Ball ---
    ball_color = disp.get("ball_color", "white")
    ball = Ball(x=0.0, y=0.0, vx=2.0, vy=1.3,
                radius=field["ball_radius"], color=ball_color)
    ball_patch = Circle((ball.x, ball.y), ball.radius,
                        facecolor=ball.color, edgecolor="black", linewidth=1, zorder=6)
    if disp.get("show_ball", True):
        ax.add_patch(ball_patch)

    # --- Animation ---
    dt = 0.04  # seconds per frame (~25 fps)

    def update(_frame):
        if gc_receiver is not None:
            gc = gc_receiver.latest()
            if gc is not None:
                _update_gc_artists(gc_artists, gc, teams_map)

        if receiver is not None:
            msg = receiver.latest()
            if msg is not None:
                for agent_msg in msg.agents:
                    idx = agent_msg.id - 1
                    if 0 <= idx < len(agents):
                        a = agents[idx]
                        a.x, a.y, a.angle = agent_msg.x, agent_msg.y, agent_msg.angle
                        a.role, a.state, a.color = agent_msg.role, agent_msg.state, agent_msg.color
                if msg.ball is not None:
                    ball.x, ball.y = msg.ball.x, msg.ball.y
        else:
            for agent in agents:
                agent.step(dt, hw, hh)
            ball.step(dt, hw, hh)

        for i, agent in enumerate(agents):
            update_agent_artists(agent, *agent_artists[i], agent_size)
        ball_patch.set_center((ball.x, ball.y))

    anim = FuncAnimation(fig, update, interval=int(dt * 1000), blit=False, cache_frame_data=False)  # noqa: F841

    plt.tight_layout()
    plt.subplots_adjust(top=0.85)
    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        if receiver is not None:
            receiver.stop()
        if gc_receiver is not None:
            gc_receiver.stop()
