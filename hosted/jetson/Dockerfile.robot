# arm64 robot image for the Jetson. /workspace/Dockerfile (the x86 one, unchanged) is built first as oraculum-arm-base;
# this adds Box64, which runs the closed x86_64 booster-motion on arm64. Box64 replaces some x86 libraries with the
# native arm64 ones ("wrapped"): the base apt list installs the X11/wayland ones; SDL2 is added here.
# lua 5.3 and glog: needed by the native aarch64 booster-motion from the T1 firmware (booster_native.sh).
FROM oraculum-arm-base
RUN apt-get update && apt-get install -y --no-install-recommends libsdl2-2.0-0 liblua5.3-0 libgoogle-glog0v5 && rm -rf /var/lib/apt/lists/*
COPY box64 /usr/local/bin/box64
# FastDDS data sharing off on the x86 side: its shared-memory mutex layout differs between x86 (Box64) and arm64
# (patch_fastrtps.py makes libfastrtps.so.2.13 in the build context from /opt/booster/lib-usr-local)
COPY libfastrtps.so.2.13 /opt/booster/lib-usr-local/libfastrtps.so.2.13
ENV BOX64_LD_LIBRARY_PATH=/opt/booster/lib:/opt/booster/lib-usr-local:/opt/booster/lib-x86_64-linux-gnu
