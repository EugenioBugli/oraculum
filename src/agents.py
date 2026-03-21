"""Agent model and dummy movement."""

import math
import random
from dataclasses import dataclass

import matplotlib.patches as patches
from matplotlib.transforms import Affine2D

# Default palette for agents
AGENT_COLORS = ["#822433", "#006778", "#000000", "#ffffff"]

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


def _body_verts(agent: Agent, s: float) -> list[tuple]:
    """Compute the 3 vertices of the arrowhead triangle in world frame.

    Triangle centroid sits at (agent.x, agent.y) so the number label is
    always centered inside the shape.
    Local frame: forward = +x, lateral = +y.
      tip:        ( 2s,   0   )
      back-left:  (-2s,  +1.2s)
      back-right: (-2s,  -1.2s)
    Centroid: ((2s - 2s - 2s)/3, 0) = (-2s/3, 0)
    The centroid sits in the wide body section, so (agent.x, agent.y)
    already lands in the right spot for the number label — no angle-dependent
    offset needed.
    """
    c, si = math.cos(agent.angle), math.sin(agent.angle)

    def to_world(fwd: float, lat: float) -> tuple:
        return (agent.x + fwd * c - lat * si,
                agent.y + fwd * si + lat * c)

    return [
        to_world(2 * s, 0),            # tip
        to_world(-2.0 * s, +1.2 * s),  # back-left
        to_world(-2.0 * s, -1.2 * s),  # back-right
    ]



def _triangle_centroid(agent: Agent, s: float) -> tuple:
    verts = _body_verts(agent, s)
    return (sum(v[0] for v in verts) / 3, sum(v[1] for v in verts) / 3)


def _text_transform(agent: Agent, s: float, ax):
    """Affine transform that rotates the label and places it at the centroid.

    The text is defined at (0, 0); this transform handles both rotation and
    translation in one matrix, avoiding any pixel-snapping drift.
    """
    cx, cy = _triangle_centroid(agent, s)
    return (Affine2D()
            .rotate(agent.angle - math.pi / 2)
            .translate(cx, cy)
            + ax.transData)


def make_agent_artists(ax, agent: Agent, index: int, size: float) -> tuple:
    """Create and add to *ax* the body polygon and number label for *agent*.

    Returns (body_patch, text) — both support in-place updates.
    """
    body = patches.Polygon(
        _body_verts(agent, size),
        closed=True, facecolor=agent.color, edgecolor="black",
        linewidth=1, zorder=10,
    )
    ax.add_patch(body)

    text = ax.text(
        0, 0, str(index + 1),
        color=_label_color(agent.color), ha="center", va="center",
        fontsize=15, fontweight="bold", zorder=11,
        transform=_text_transform(agent, size, ax),
    )
    return body, text


def update_agent_artists(agent: Agent, body: patches.Polygon, text, size: float) -> None:
    """Update existing artists in-place (no remove/re-add needed)."""
    body.set_xy(_body_verts(agent, size))
    text.set_color(_label_color(agent.color))
    text.set_transform(_text_transform(agent, size, text.axes))

