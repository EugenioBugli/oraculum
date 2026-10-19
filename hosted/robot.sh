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
exec /usr/bin/supervisord -n -c /workspace/scripts/supervisord.conf
