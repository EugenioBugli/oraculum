#!/bin/bash
# Measurement only (Jetson copy of the robot code, fall analysis): log the walk command sent to booster-motion at most
# every 100 ms ("[MoveCmd] vx vy vyaw", after Maximus's NaN/deadband handling). Run in the workspace. Idempotent.
set -euo pipefail
f=src/app/booster/BoosterRobotPortal.cpp
grep -q 'MoveCmd' $f || python3 - "$f" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
old = "    return motionClient_.Move(vx, vy, vyaw);\n"
new = ("    {  // jetson fall analysis: walk command at most every 100 ms\n"
       "        static uint64_t lastMoveLogMs = 0;\n"
       "        const uint64_t nowMs = static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(\n"
       "            std::chrono::steady_clock::now().time_since_epoch()).count());\n"
       "        if (nowMs - lastMoveLogMs >= 100) {\n"
       "            lastMoveLogMs = nowMs;\n"
       "            LOG_INFO(\"MoveCmd\", vx << \" \" << vy << \" \" << vyaw);\n"
       "        }\n"
       "    }\n" + old)
assert s.count(old) == 1, "Move call not found once"
s = s.replace(old, new)
if "#include <chrono>" not in s:
    s = "#include <chrono>\n" + s
if '"Log.h"' not in s:
    s = s.replace("#include <chrono>\n", '#include <chrono>\n#include "Log.h"\n', 1)
open(p, "w").write(s)
PY
grep -q 'MoveCmd' $f
