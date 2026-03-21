"""Figure setup, animation loop, and entry point."""

import os
import sys

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from .config import load_config
from .field import draw_field
from matplotlib.patches import Circle
from .agents import create_agents, make_agent_artists, update_agent_artists, Ball, draw_agent_legend


_ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")


def main() -> None:
    root = os.path.abspath(_ROOT_DIR)

    try:
        cfg, field, field_name = load_config(root)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    disp = cfg.get("display", {})
    title = disp.get("title", "Field Viewer")

    W = field["width"]
    H = field["height"]
    hw, hh = W / 2, H / 2
    margin = max(W, H) * 0.12

    # --- Figure setup ---
    fig_w = 16
    fig_h_field = fig_w * (H + 2 * margin) / (W + 2 * margin)
    legend_h = 1.1  # inches
    fig, (ax, ax_leg) = plt.subplots(
        2, 1,
        figsize=(fig_w, fig_h_field + legend_h),
        gridspec_kw={"height_ratios": [fig_h_field, legend_h], "hspace": 0.02},
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
                 color="#822433", fontsize=30, fontweight="bold",
                 fontfamily="serif")

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
        for agent in agents:
            agent.step(dt, hw, hh)
        for i, agent in enumerate(agents):
            update_agent_artists(agent, *agent_artists[i], agent_size)

        ball.step(dt, hw, hh)
        ball_patch.set_center((ball.x, ball.y))

    anim = FuncAnimation(fig, update, interval=int(dt * 1000), blit=False, cache_frame_data=False)  # noqa: F841

    plt.tight_layout()
    plt.subplots_adjust(top=0.93)
    try:
        plt.show()
    except KeyboardInterrupt:
        pass
