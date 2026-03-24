"""Agent model and dummy movement."""

import math
import random
from dataclasses import dataclass

import matplotlib.patches as patches
from matplotlib.transforms import Affine2D

# Default palette for agents
AGENT_COLORS = ["#822433", "#006778", "#000000", "#ffffff"]
AGENT_ROLES = ["G", "D", "M", "A"]
AGENT_STATES = ["I", "R", "S", "P", "X"] 

_LIGHT_COLORS = {"#ffffff", "white"}


def _label_color(agent_color: str) -> str:
    return "black" if agent_color.lower() in _LIGHT_COLORS else "white"


@dataclass
class Agent:
    x: float
    y: float
    speed: float
    angle: float  # radians, direction of movement
    color: str
    role: str = "M"
    state: str = "R"

    @property
    def vx(self) -> float:
        return self.speed * math.cos(self.angle)

    @property
    def vy(self) -> float:
        return self.speed * math.sin(self.angle)

    def step(self, dt: float, hw: float, hh: float) -> None:
        """Advance position by *dt* seconds; bounce off field boundaries."""
        self.x += self.vx * dt
        self.y += self.vy * dt

        if not (-hw < self.x < hw):
            self.angle = math.pi - self.angle
            self.x = max(-hw + 1e-3, min(hw - 1e-3, self.x))

        if not (-hh < self.y < hh):
            self.angle = -self.angle
            self.y = max(-hh + 1e-3, min(hh - 1e-3, self.y))


@dataclass
class Ball:
    x: float
    y: float
    vx: float
    vy: float
    radius: float
    color: str = "orange"

    def step(self, dt: float, hw: float, hh: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        r = self.radius
        if not (-(hw - r) < self.x < (hw - r)):
            self.vx *= -1
            self.x = max(-(hw - r), min(hw - r, self.x))
        if not (-(hh - r) < self.y < (hh - r)):
            self.vy *= -1
            self.y = max(-(hh - r), min(hh - r, self.y))


def create_agents(n: int, hw: float, hh: float, speed: float = 1.5, seed: int = 42) -> list[Agent]:
    """Create *n* agents with random positions and directions inside the field."""
    rng = random.Random(seed)
    return [
        Agent(
            x=rng.uniform(-hw * 0.8, hw * 0.8),
            y=rng.uniform(-hh * 0.8, hh * 0.8),
            speed=speed * rng.uniform(0.7, 1.3),
            angle=rng.uniform(0, 2 * math.pi),
            color=AGENT_COLORS[i % len(AGENT_COLORS)],
            role=AGENT_ROLES[i % len(AGENT_ROLES)],
            state=AGENT_STATES[i % len(AGENT_STATES)],
        )
        for i in range(n)
    ]


def _pentagon_verts(agent: Agent, s: float) -> list:
    """Pentagon with an elongated front vertex pointing in the heading direction."""
    radii = [s * 2.2, s * 1.0, s * 1.0, s * 1.0, s * 1.0]
    return [
        (agent.x + radii[k] * math.cos(agent.angle + k * 2 * math.pi / 5),
         agent.y + radii[k] * math.sin(agent.angle + k * 2 * math.pi / 5))
        for k in range(5)
    ]


def _text_transform(agent: Agent, ax):
    """Rotate the label to match movement direction and place it at agent centre."""
    return (Affine2D()
            .rotate(agent.angle)
            .translate(agent.x, agent.y)
            + ax.transData)


def make_agent_artists(ax, agent: Agent, index: int, size: float) -> tuple:
    """Create ellipse body and number label for *agent*.

    The ellipse is elongated along the heading direction so the shape
    visually rotates with the agent.
    Returns (body, text) — both support in-place updates.
    """
    body = patches.Polygon(
        _pentagon_verts(agent, size),
        closed=True, facecolor=agent.color, edgecolor="black", linewidth=1, zorder=10,
    )
    ax.add_patch(body)

    text = ax.text(
        0, 0, str(index + 1),
        color=_label_color(agent.color), ha="center", va="center",
        fontsize=15, fontweight="bold", zorder=11,
        transform=_text_transform(agent, ax),
    )
    return body, text


def update_agent_artists(agent: Agent, body, text, size: float) -> None:
    """Update existing artists in-place (no remove/re-add needed)."""
    body.set_xy(_pentagon_verts(agent, size))
    text.set_color(_label_color(agent.color))
    text.set_transform(_text_transform(agent, text.axes))


def draw_agent_legend(ax, agents: list) -> None:
    """Draw a static column per agent showing Player number and Role."""
    n = len(agents)
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(0, 1)
    ax.set_facecolor("#1e1e1e")
    ax.axis("off")

    rect_w, rect_h = 0.88, 0.82
    y0 = (1 - rect_h) / 2        # rectangle bottom
    y1 = y0 + rect_h              # rectangle top
    third = rect_h / 3
    d1 = y0 + third               # divider between state and role
    d2 = y0 + 2 * third           # divider between role and player

    for i, agent in enumerate(agents):
        lc = _label_color(agent.color)

        # Colored rectangle
        rect = patches.Rectangle(
            (i - rect_w / 2, y0), rect_w, rect_h,
            facecolor=agent.color, edgecolor="black", linewidth=1,
        )
        ax.add_patch(rect)

        # Divider lines
        for dy in (d1, d2):
            ax.plot([i - rect_w / 2, i + rect_w / 2], [dy, dy],
                    color=lc, linewidth=0.6, alpha=0.5)

        # "Player : N"  (top third)
        ax.text(i, (d2 + y1) / 2, f"Player : {i + 1}",
                color=lc, ha="center", va="center", fontsize=8, fontweight="bold")

        # "Role : X"  (middle third)
        ax.text(i, (d1 + d2) / 2, f"Role : {agent.role}",
                color=lc, ha="center", va="center", fontsize=8, fontweight="bold")

        # "State : X"  (bottom third)
        ax.text(i, (y0 + d1) / 2, f"State : {agent.state}",
                color=lc, ha="center", va="center", fontsize=8, fontweight="bold")

