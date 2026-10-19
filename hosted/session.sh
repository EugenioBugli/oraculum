#!/bin/bash
# One hosted simulation session in one container: virtual display, circus (1 robot), the robot stack, the oraculum
# gateway (HTTP 8080) and a browser view of the circus window (noVNC, HTTP 6080). Only 8080 and 6080 leave the
# container; all robot traffic (UDP 10006-10009, DDS, circus TCP) stays on loopback.
SCENE=${SCENE:-/opt/session/scenes/1v0.yaml}
export DISPLAY=:1
Xvfb :1 -screen 0 1600x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
sleep 1
# ORACULUM_ACCESS_TOKEN (a Modal secret, one per session) guards both the gateway and the VNC view.
x11vnc -storepasswd "${ORACULUM_ACCESS_TOKEN:?no access token}" /tmp/vncpass >/dev/null 2>&1
x11vnc -display :1 -forever -shared -rfbauth /tmp/vncpass -rfbport 5900 -localhost -quiet >/tmp/x11vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
# The session's referee (src/sim_gc.py): team 8 = the robot of scenes/1v0.yaml, team 70 = an empty opponent.
(cd /opt/oraculum && ORACULUM_SIM_GC=${SIM_GC_TEAMS:-8,70} ORACULUM_CONTROL_IP=127.0.0.1 python3 -u src/control_server.py >/tmp/gateway.log 2>&1 &)
cd /opt/circus
export CIRCUS_ROBOT_LAUNCHER=/opt/session/robot.sh FRAMEWORK_PATH=/workspace
export INFERENCE_BACKEND=${INFERENCE_BACKEND:-onnx} LIBGL_ALWAYS_SOFTWARE=1
# llvmpipe (software OpenGL) starts one render thread per host CPU it sees; 2 threads cut the cost of the circus window.
export LP_NUM_THREADS=${LP_NUM_THREADS:-2}
./build/circus --scene "$SCENE" --framework /opt/session/framework.yaml --connect-mode "${CONNECT_MODE:-shm}" >/tmp/circus.log 2>&1  # shm: robot commands reach circus only through shared memory
echo "circus exited with $?" >>/tmp/circus.log
sleep infinity  # keep the gateway and the logs; the sandbox's idle_timeout and timeout end the session
