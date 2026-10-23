#!/bin/bash
# Server B of a split session: it runs the containers of the teams that circus on server A starts over SSH
# (A: CIRCUS_DOCKER_SOCK_TEAM<n>=/run/docker_b.sock, forwarded with ssh -L to this host's /var/run/docker.sock).
# Its robots dial SERVER_IP 172.21.0.1:5555 (fixed by circus); socat relays that to circus on A over the private network.
# Telemetry and the referee stay local: this host runs its own gateway with the simulated referee for its robots.
#   SCENE=/opt/session/5v5.yaml TEAMS_HERE=2 /opt/session/split_peer.sh <A private ip>
set -u
A=${1:?usage: split_peer.sh <private ip of server A>}
SCENE=${SCENE:-/opt/session/5v5.yaml}
TEAMS_HERE=${TEAMS_HERE:-2}
/opt/session/cleanup.sh
# The same network circus creates on A (include/CircusNetwork.h, circus 48154ea1)
docker network create --driver bridge --subnet 172.21.0.0/16 --ip-range 172.21.0.0/16 --gateway 172.21.0.1 \
    -o com.docker.network.bridge.name=docker-circus -o com.docker.network.bridge.enable_ip_masquerade=false \
    -o com.docker.network.driver.mtu=1500 -o com.docker.network.container_iface_prefix=circus CIRCUS_network >/dev/null
TOKEN_FILE=/run/oraculum/token
if [ ! -s "$TOKEN_FILE" ]; then
    mkdir -p /run/oraculum
    (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(16))' > "$TOKEN_FILE")
fi
export ORACULUM_ACCESS_TOKEN=$(cat "$TOKEN_FILE")
trap 'kill $(jobs -p) 2>/dev/null; /opt/session/cleanup.sh' EXIT
Xvfb :1 -screen 0 640x480x24 -nolisten tcp &   # circus gives the containers DISPLAY=:1 and the X11 socket
# nodelay on both legs: one state per 2 ms substep must not wait for Nagle
socat TCP-LISTEN:5555,bind=172.21.0.1,fork,reuseaddr,nodelay TCP:"$A":5555,nodelay &
read -r TEAMS IPS < <(python3 - "$SCENE" "$TEAMS_HERE" <<'PY'
import sys

import yaml

teams = list(yaml.safe_load(open(sys.argv[1]))["teams"].values())
here = {int(t) for t in sys.argv[2].split(",")}
print(",".join(str(t["number"]) for t in teams[:2]),
      ",".join(f"172.21.{t['number']}.{p['number'] + 10}" for t in teams if t["number"] in here for p in t["players"]))
PY
)
cd /opt/oraculum && ORACULUM_SIM_GC=$TEAMS ORACULUM_GC_TARGETS=$IPS python3 -u src/control_server.py
