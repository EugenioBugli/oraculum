"""Test full viewer rendering layout to see if it shows as a horizontal line."""
import matplotlib
matplotlib.use('TkAgg')

import os
import sys
import time
import matplotlib.pyplot as plt
import atexit

from src.config import load_config, load_teams
from src.field import draw_field
from src.agents import create_agents, make_agent_artists, draw_agent_legend, Ball
from matplotlib.patches import Circle

root = os.path.abspath('.')
cfg, field, field_name = load_config(root)
teams_map = load_teams(root)

W = field["width"]
H = field["height"]
hw, hh = W / 2, H / 2
margin = max(W, H) * 0.06

fig_w = 10
fig_h_field = fig_w * (H + 2 * margin) / (W + 2 * margin)
legend_h = 0.75

print(f"[*] Field: {W}x{H}, margin: {margin}")
print(f"[*] Fig dimensions: width={fig_w}, field_height={fig_h_field}, legend_height={legend_h}")

fig, (ax, ax_leg) = plt.subplots(
    2, 1,
    figsize=(fig_w, fig_h_field + legend_h),
    gridspec_kw={"height_ratios": [fig_h_field, legend_h], "hspace": 0.0},
)

fig.patch.set_facecolor("#1e1e1e")
fig.suptitle("Oraculum Render Test", color="#822433", fontsize=22, fontweight="bold", fontfamily="serif")

draw_field(ax, field, cfg)
ax.set_xlim(-hw - margin, hw + margin)
ax.set_ylim(-hh - margin, hh + margin)
ax.set_aspect("equal")
ax.axis("off")

# Agents
n_agents = cfg.get("agents", {}).get("count", 5)
speed = cfg.get("agents", {}).get("speed", 1.5)
agents = create_agents(n_agents, hw, hh, speed=speed)
agent_size = min(W, H) * 0.032

agent_artists = []
for i, agent in enumerate(agents):
    agent_artists.append(make_agent_artists(ax, agent, i, agent_size))

# Legend
draw_agent_legend(ax_leg, agents)

# Ball
ball_color = cfg.get("display", {}).get("ball_color", "white")
ball = Ball(x=0.0, y=0.0, vx=2.0, vy=1.3, radius=field["ball_radius"], color=ball_color)
ball_patch = Circle((ball.x, ball.y), ball.radius, facecolor=ball.color, edgecolor="black", linewidth=1, zorder=6)
ax.add_patch(ball_patch)

plt.tight_layout()
plt.subplots_adjust(top=0.85)

print("[*] Saving figure to viewer_render_test.png...")
fig.savefig("viewer_render_test.png")
print("[*] Saved.")
print("[*] Test complete")
