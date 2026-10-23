#!/bin/bash
# Build a Hetzner session VM (Ubuntu 24.04, as root, after hosted/vm/push.sh). Estimated 35-60 min on 8 vCPU.
# Then smoke-test 2 robots, snapshot the server (hetzner.py snapshot) and delete it (hetzner.py delete).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
# build-essential + libgl1-mesa-dev: circus takes its libraries from pixi but the compiler, make and the OpenGL headers
# from the host (on Modal the ros:humble base image had them)
apt-get install -yq ca-certificates curl git rsync patch socat build-essential libgl1-mesa-dev xvfb x11vnc novnc websockify \
    libgl1-mesa-dri libglx-mesa0 libegl-mesa0 mesa-utils python3-yaml libxcb-cursor0 libxkbcommon-x11-0 fonts-dejavu-core

# Docker Engine 28.2 or newer (API 1.50, needed by circus's GPU detection): Docker's own apt repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
     "https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
     > /etc/apt/sources.list.d/docker.list
apt-get update -q && apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin
api=$(docker version --format '{{.Server.APIVersion}}')
python3 -c "import sys; sys.exit(tuple(map(int, '$api'.split('.'))) < (1, 50))" || { echo "Docker API $api < 1.50" >&2; exit 1; }

curl -fsSL https://pixi.sh/install.sh | bash
export PATH=/root/.pixi/bin:$PATH

# The robot image (simbridge + booster-motion) first, while /workspace has no .pixi and no build (small build context)
cd /workspace && docker build -t spqr_maximus_bridge .
# circus (a fresh build folder: CMake caches a failed compiler search)
cd /opt/circus && rm -rf build && pixi install && JOBS=$(nproc) pixi run compile
# Maximus (CPU only: TensorRT off; the CUDA packages install without a GPU)
cd /workspace && CONDA_OVERRIDE_CUDA=12.0 pixi install
CONDA_OVERRIDE_CUDA=12.0 EXTRA_CMAKE_ARGS=-DENABLE_TENSORRT=OFF JOBS=$(nproc) pixi run compile --skip-gcdo-update

# Robot config: oraculum link on, Rerun to /dev/null, no camera. Edited in place: the robot entrypoint fixes
# SPQR_CONFIG_ROOT to /workspace/src/app/config.
cd /workspace/src/app/config
# The scenario comes only from settings.yaml, and branches commit different ones (mappazzone: "real", which runs the
# camera perception stack and dies in the simulator). Hosted sessions run sim_fast (simulator oracle data, no camera).
sed -i -E "s/^scenario: \"[a-z_]+\"/scenario: \"${SCENARIO:-sim_fast}\"/" settings.yaml
grep -q "^scenario: \"${SCENARIO:-sim_fast}\"" settings.yaml
sed -i 's/^useRerun: false/useRerun: true /' deploy.yaml
sed -i 's|^  mode: "connect"|  mode: "save"|; s|^  savePath: .*|  savePath: "/dev/null"|; s|^    rgb: true|    rgb: false|' settings.yaml
grep -q '^useRerun: true' deploy.yaml && grep -q '^  mode: "save"' settings.yaml

touch /root/.Xauthority   # else Docker creates it as a folder when circus mounts it
chmod +x /opt/session/*.sh
install -m 644 /opt/session/oraculum-sim.service /etc/systemd/system/
systemctl daemon-reload
echo "built. Smoke test (2 robots): SCENE=/opt/session/1v1.yaml SIM_S=60 /opt/session/measure_rtf.sh"
echo "Session at boot: systemctl enable oraculum-sim (enable it last, just before the snapshot)"
