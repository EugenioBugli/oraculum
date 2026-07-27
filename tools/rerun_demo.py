"""Rerun 3D Visualizer Demo for Oraculum & SPQR RoboCup Telemetry.
"""
import math
import time
import rerun as rr

def main():
    # Initialize Rerun session
    rr.init("Oraculum RoboCup Viewer", spawn=True)

    # Log 3D Field Boundaries & Lines
    HW = 9.0   # half width (18m)
    HH = 6.0   # half height (12m)

    # Field Line segments
    field_lines = [
        # Outer border
        [-HW, -HH, 0], [HW, -HH, 0],
        [HW, -HH, 0], [HW, HH, 0],
        [HW, HH, 0], [-HW, HH, 0],
        [-HW, HH, 0], [-HW, -HH, 0],
        # Center line
        [0, -HH, 0], [0, HH, 0]
    ]

    rr.log(
        "field/lines",
        rr.LineStrips3D(
            strips=[field_lines[i:i+2] for i in range(0, len(field_lines), 2)],
            colors=[0, 255, 136],
            radii=0.03
        )
    )

    # Log Center Circle
    circle_pts = []
    r = 1.5
    for deg in range(0, 365, 5):
        rad = math.radians(deg)
        circle_pts.append([r * math.cos(rad), r * math.sin(rad), 0.0])
    
    rr.log("field/center_circle", rr.LineStrips3D(strips=[circle_pts], colors=[0, 210, 255], radii=0.02))

    # Log 3D Goals
    goal_left = [
        [-HW, -0.8, 0], [-HW, -0.8, 0.8],
        [-HW, -0.8, 0.8], [-HW, 0.8, 0.8],
        [-HW, 0.8, 0.8], [-HW, 0.8, 0],
    ]
    goal_right = [
        [HW, -0.8, 0], [HW, -0.8, 0.8],
        [HW, -0.8, 0.8], [HW, 0.8, 0.8],
        [HW, 0.8, 0.8], [HW, 0.8, 0],
    ]
    rr.log("field/goals", rr.LineStrips3D(strips=[goal_left, goal_right], colors=[255, 255, 255], radii=0.04))

    # Log Robots
    robots = [
        {"id": 1, "pos": [2.5, 1.0, 0.3], "color": [99, 102, 241], "role": "Striker"},
        {"id": 2, "pos": [-7.5, 0.0, 0.3], "color": [0, 210, 255], "role": "Goalie"},
        {"id": 3, "pos": [-3.0, -2.0, 0.3], "color": [0, 255, 136], "role": "Defender"},
        {"id": 4, "pos": [0.5, 3.0, 0.3], "color": [255, 159, 28], "role": "Midfielder"},
    ]

    for bot in robots:
        rr.log(
            f"robots/bot_{bot['id']}",
            rr.Boxes3D(
                centers=[bot["pos"]],
                half_sizes=[[0.2, 0.2, 0.3]],
                colors=[bot["color"]],
                labels=[f"Robot #{bot['id']} ({bot['role']})"]
            )
        )

    # Log Ball
    rr.log("ball", rr.Points3D(positions=[[3.0, 1.2, 0.11]], colors=[[255, 255, 0]], radii=0.15))

    # Log C++ Debug Drawing Streams (Pass Line & Target Vector)
    rr.log("debug/pass_vector", rr.LineStrips3D(strips=[[[2.5, 1.0, 0.1], [3.0, 1.2, 0.1]]], colors=[0, 255, 136], radii=0.02))
    rr.log("debug/target_pose", rr.Points3D(positions=[[5.0, 0.5, 0.0]], colors=[[255, 60, 106]], radii=0.12, labels=["Striker Target"]))

    print("[Rerun] Logged entities successfully into Rerun 3D Viewer.")
    
    while True:
        time.sleep(1.0)

if __name__ == "__main__":
    main()
