# Build host for export_scene.sh: pixi (circus's own environment; it has no make, so apt adds it)
# + Python mujoco 3.3.3 + OSMesa for the reference render.
FROM ghcr.io/prefix-dev/pixi:0.70.2-noble
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates make python3-venv libosmesa6 \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir mujoco==3.3.3 PyOpenGL==3.1.9
ENV PYTHON=/venv/bin/python MUJOCO_GL=osmesa PYOPENGL_PLATFORM=osmesa
COPY export_scene.sh export_scene.cpp exporter.cmake package_scene.py /tools/
ENTRYPOINT ["/tools/export_scene.sh"]
