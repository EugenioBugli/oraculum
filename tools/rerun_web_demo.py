import math
import time
import rerun as rr

def main():
    rr.init("Oraculum RoboCup Viewer")
    rr.serve_web_viewer(web_port=9090)

    HW = 9.0
    HH = 6.0

    field_lines = [
        [-HW, -HH, 0], [HW, -HH, 0],
        [HW, -HH, 0], [HW, HH, 0],
        [HW, HH, 0], [-HW, HH, 0],
        [-HW, HH, 0], [-HW, -HH, 0],
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

    circle_pts = []
    r = 1.5
    for deg in range(0, 365, 5):
        rad = math.radians(deg)
        circle_pts.append([r * math.cos(rad), r * math.sin(rad), 0.0])
    
    rr.log("field/center_circle", rr.LineStrips3D(strips=[circle_pts], colors=[0, 210, 255], radii=0.02))

    robots = [
        {"id": 1, "pos": [2.5, 1.0, 0.3], "color": [99, 102, 241], "role": "Striker"},
        {"id": 2, "pos": [-7.5, 0.0, 0.3], "color": [0, 210, 255], "role": "Goalie"},
        {"id": 3, "pos": [-3.0, -2.0, 0.3], "color": [0, 255, 136], "role": "Defender"},
    ]

    for bot in robots:
        rr.log(
            f"robots/bot_{bot['id']}",
            rr.Boxes3D(
                centers=[bot["pos"]],
                half_sizes=[[0.25, 0.25, 0.35]],
                colors=[bot["color"]],
                labels=[f"Robot #{bot['id']} ({bot['role']})"]
            )
        )

    rr.log("ball", rr.Points3D(positions=[[3.0, 1.2, 0.11]], colors=[[255, 255, 0]], radii=0.15))
    rr.log("debug/pass_vector", rr.LineStrips3D(strips=[[[2.5, 1.0, 0.1], [3.0, 1.2, 0.1]]], colors=[0, 255, 136], radii=0.02))

    print("[Rerun] Serving web viewer at http://localhost:9090")
    while True:
        time.sleep(1.0)

if __name__ == "__main__":
    main()
