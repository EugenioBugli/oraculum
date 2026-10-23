#!/usr/bin/env python3
"""Fall analysis: for each robot log folder, find booster-motion's switch to Damping (Maximus sends mode 0 when its
FallDetector fires) and print the walk commands booster-motion received in the 3 s before it, plus their statistics.
    python3 fall_report.py <folder with booster-motion.log> [...]
"""
import re
import sys
from datetime import datetime

TS = re.compile(r"^\[(\d\d-\d\d \d\d:\d\d:\d\d\.\d+)\]")
MOVE = re.compile(r"Move Command: (\S+), (\S+), (\S+)")


def t(line):
    m = TS.match(line)
    return datetime.strptime(m.group(1), "%m-%d %H:%M:%S.%f") if m else None


for d in sys.argv[1:]:
    lines = open(f"{d}/booster-motion.log", errors="replace").read().splitlines()
    moves = [(t(x), tuple(map(float, MOVE.search(x).groups()))) for x in lines if "Move Command" in x and t(x)]
    damp = [t(x) for x in lines if "to: Damping" in x and t(x)]
    print(f"== {d}: {len(moves)} walk commands, {len(damp)} switch(es) to Damping")
    if moves:
        print(f"   whole run: max |vx| {max(abs(m[1][0]) for m in moves):.2f}, max |vy| {max(abs(m[1][1]) for m in moves):.2f}, "
              f"max |vyaw| {max(abs(m[1][2]) for m in moves):.2f}")
    for td in damp[:1]:
        w = [m for m in moves if 0 <= (td - m[0]).total_seconds() <= 3]
        if not w:
            print(f"   Damping at {td:%H:%M:%S.%f}: no walk command in the 3 s before")
            continue
        vx = [m[1][0] for m in w]
        vy = [m[1][1] for m in w]
        vyaw = [m[1][2] for m in w]
        print(f"   Damping at {td:%H:%M:%S.%f}; 3 s before: {len(w)} commands, vx {min(vx):.2f}..{max(vx):.2f} "
              f"(mean {sum(vx) / len(vx):.2f}), vy {min(vy):.2f}..{max(vy):.2f}, vyaw {min(vyaw):.2f}..{max(vyaw):.2f}")
        print(f"   last command: {w[-1][1]} at {w[-1][0]:%H:%M:%S.%f}")
