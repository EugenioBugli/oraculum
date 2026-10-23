#!/bin/bash
# Test only (fall analysis, isolation test): env CIRCUS_BALL_POS="x y z" puts the ball there at scene creation (e.g.
# "0 40 0.11", far outside the field: no ball in view). Unset = upstream behaviour. Run in the circus checkout.
set -euo pipefail
f=src/FieldGenerator.cpp
grep -q CIRCUS_BALL_POS $f || python3 - "$f" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
old = '    ballPosStream << initialPosition[0] << " " << initialPosition[1] << " " << initialPosition[2];\n'
new = ('    if (const char* bp = std::getenv("CIRCUS_BALL_POS"))  // jetson fall analysis: ball placement override\n'
       '        ballPosStream << bp;\n'
       '    else\n'
       '        ballPosStream << initialPosition[0] << " " << initialPosition[1] << " " << initialPosition[2];\n')
assert s.count(old) == 1
s = s.replace(old, new)
if "#include <cstdlib>" not in s:
    s = "#include <cstdlib>\n" + s
open(p, "w").write(s)
PY
grep -q CIRCUS_BALL_POS $f
