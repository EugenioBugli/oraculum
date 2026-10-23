#!/bin/bash
# One robot of a hosted session, started by the patched circus (CIRCUS_ROBOT_LAUNCHER). It does what the robot
# container's entrypoint (spqrbooster2026/scripts/docker_entrypoint.sh) does, as plain processes: Modal has no Docker.
# circus passes ROBOT_NAME, SERVER_IP=127.0.0.1, CIRCUS_PORT, TEAM_NUMBER, PLAYER_NUMBER, TEAM_COLOR, ... in the env.
source /opt/ros/humble/setup.bash
export FASTRTPS_DEFAULT_PROFILES_FILE=/opt/booster/fastdds_profile.xml
export SPQR_CONFIG_ROOT=/opt/session/config      # copy of the robot config with useRerun: true (debug link on)
export SPQR_MODEL_PATH=/workspace/models/
export ORACULUM_HOST=127.0.0.1                    # the session's own gateway (DebugMessageSender)
export LD_PRELOAD=/opt/session/libnort.so          # real-time calls succeed without effect (see nort.c)
mkdir -p /var/log
# One host runs many robots, so give each its own log dir and supervisord config (the template hard-codes
# /var/log/{booster-motion,simbridge,maximus}.log, which 10 robots would overwrite).
LOGD=/var/log/${ROBOT_NAME:-robot}; mkdir -p "$LOGD"
CONF=/tmp/supervisord-${ROBOT_NAME:-robot}.conf
sed "s#/var/log/#$LOGD/#g" /workspace/scripts/supervisord.conf > "$CONF"
export ORACULUM_SUPERVISORD_CONF="$CONF"
# robot_netns.py isolates this robot in its own network namespace when ORACULUM_ISOLATE=1 (many robots on one
# host); otherwise it just execs supervisord (the unchanged single-robot path).
exec python3 /opt/session/robot_netns.py
