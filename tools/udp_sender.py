"""Fake data sender — simulates agents and ball, broadcasts GameStateMsg over UDP.

Run this in a separate terminal while the viewer is open:
    python tools/udp_sender.py

The host/port must match the [socket] section in config.yaml.
"""

import math
import random
import sys
import time
import os

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.agents import Agent, Ball, create_agents, AGENT_COLORS, AGENT_ROLES, AGENT_STATES
from src.socket_client import AgentMsg, BallMsg, GameStateMsg, DrawingMsg
from src.socket_host import UDPSender

# ---------------------------------------------------------------------------
# Configuration — keep in sync with config.yaml [socket] section
# ---------------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 10006
FPS  = 25

# Field half-dimensions in metres (must match the field yaml used by the viewer)
HW = 9.0   # half-width  (fieldAdultSize: 18 m wide)
HH = 6.0   # half-height (fieldAdultSize: 12 m tall)

N_AGENTS = 7


def build_msg(agents: list[Agent], ball: Ball) -> GameStateMsg:
    # Simulated drawings
    drawings = [
        # Field center circle indicator
        DrawingMsg(
            type="circle",
            path="/field/center_circle",
            coords=[0.0, 0.0],
            color=[0, 210, 255],
            size=1.5
        ),
        # Dynamic box centered on the ball
        DrawingMsg(
            type="box",
            path="/ball/bounding_box",
            coords=[ball.x, ball.y, 0.6, 0.6],
            color=[255, 60, 106],
            size=0.01
        ),
        # Vector line from first robot to the ball
        DrawingMsg(
            type="line",
            path="/coordination/pass_line",
            coords=[agents[0].x, agents[0].y, ball.x, ball.y],
            color=[0, 255, 136],
            size=0.02
        ),
        # Striker goal target point
        DrawingMsg(
            type="point",
            path="/striker/target_pose",
            coords=[3.5, 1.5],
            color=[255, 255, 0],
            size=0.08
        ),
        # Goalkeeper field-of-view arc
        DrawingMsg(
            type="arc",
            path="/goalie/view_arc",
            coords=[-HW + 0.5, 0.0, 2.5, -45, 45],
            color=[200, 200, 200],
            size=0.02
        )
    ]

    return GameStateMsg(
        agents=[
            AgentMsg(
                id=i + 1,
                x=round(a.x, 4),
                y=round(a.y, 4),
                angle=round(a.angle, 4),
                role=a.role,
                state=a.state,
                color=a.color,
            )
            for i, a in enumerate(agents)
        ],
        ball=BallMsg(x=round(ball.x, 4), y=round(ball.y, 4)),
        drawings=drawings
    )


def main() -> None:
    agents = create_agents(N_AGENTS, HW, HH, speed=1.5, seed=random.randint(0, 9999))
    ball   = Ball(x=0.0, y=0.0, vx=2.5, vy=1.8, radius=0.11, color="white")

    dt = 1.0 / FPS

    print(f"[udp_sender] Sending to {HOST}:{PORT} at {FPS} fps  (Ctrl+C to stop)")

    with UDPSender(HOST, PORT) as host:
        try:
            while True:
                t0 = time.monotonic()

                for agent in agents:
                    agent.step(dt, HW, HH)
                ball.step(dt, HW, HH)

                # Occasionally randomise role/state to show legend updates
                for agent in agents:
                    if random.random() < 0.002:
                        agent.state = random.choice(AGENT_STATES)
                    if random.random() < 0.001:
                        agent.role = random.choice(AGENT_ROLES)

                host.send(build_msg(agents, ball))

                elapsed = time.monotonic() - t0
                time.sleep(max(0.0, dt - elapsed))

        except KeyboardInterrupt:
            print("\n[udp_sender] Stopped.")


if __name__ == "__main__":
    main()
