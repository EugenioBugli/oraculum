"""Agent model and dummy movement."""

import math
import random
from dataclasses import dataclass

import matplotlib.patches as patches

# Default palette for agents
AGENT_COLORS = ["#ff4444", "#4499ff", "#ffee44", "#44ff99", "#ff88ff", "#ff9922"]


@dataclass
class Agent:
    x: float
    y: float
    speed: float
    angle: float  # radians, direction of movement
    color: str

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
        )
        for i in range(n)
    ]


def _body_verts(agent: Agent, s: float, tip_len: float) -> list[tuple]:
    """Compute the 5 vertices of the agent body (square + fused tip) in world frame.

    The body is a square with a triangular nose on the front side, all rotated
    to match agent.angle. Local frame: forward = +x, lateral = +y.
    """
    c, si = math.cos(agent.angle), math.sin(agent.angle)

    def to_world(fwd: float, lat: float) -> tuple:
        return (agent.x + fwd * c - lat * si,
                agent.y + fwd * si + lat * c)

    return [
        to_world(-s, -s),        # back-right
        to_world(-s, +s),        # back-left
        to_world(+s, +s),        # front-left corner
        to_world(+s + tip_len, 0),  # tip
        to_world(+s, -s),        # front-right corner
    ]


def make_agent_artists(ax, agent: Agent, index: int, size: float) -> tuple:
    """Create and add to *ax* the body polygon and number label for *agent*.

    Returns (body_patch, text) — both support in-place updates.
    """
    tip_len = size * 0.7
    body = patches.Polygon(
        _body_verts(agent, size, tip_len),
        closed=True, facecolor=agent.color, edgecolor="black",
        linewidth=1, zorder=10,
    )
    ax.add_patch(body)

    text = ax.text(
        agent.x, agent.y, str(index + 1),
        color="black", ha="center", va="center",
        fontsize=18, fontweight="bold", zorder=11,
        rotation=math.degrees(agent.angle),
    )
    return body, text


def update_agent_artists(agent: Agent, body: patches.Polygon, text, size: float) -> None:
    """Update existing artists in-place (no remove/re-add needed)."""
    body.set_xy(_body_verts(agent, size, size * 0.7))
    text.set_position((agent.x, agent.y))
    text.set_rotation(math.degrees(agent.angle))
