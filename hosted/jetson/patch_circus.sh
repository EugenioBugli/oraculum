#!/bin/bash
# Make circus build and run on the Jetson (aarch64). Run in the circus checkout. Idempotent.
# 1. pixi.toml lists only linux-64 and osx-arm64: add linux-aarch64 with the same compiler/GL packages as linux-64.
# 2. Docker 28+ adds an iptables raw-table rule for every container on a bridge; the Jetson kernel has no raw table,
#    so CIRCUS_network gets gateway_mode_ipv4=nat-unprotected (skips that rule).
set -euo pipefail
grep -q '"linux-aarch64"' pixi.toml || {
    sed -i 's/^platforms = \["osx-arm64", "linux-64"\]/platforms = ["osx-arm64", "linux-64", "linux-aarch64"]/' pixi.toml
    cat >> pixi.toml <<'TOML'

[target.linux-aarch64.dependencies]
gcc_linux-aarch64 = ">=14.3.0,<15"
gxx_linux-aarch64 = ">=14.3.0,<15"
sysroot_linux-aarch64 = ">=2.34"
libgl-devel = "==1.7.0"
libegl-devel = "==1.7.0"
TOML
}
grep -q '"linux-aarch64"' pixi.toml
grep -q gateway_mode_ipv4 include/CircusNetwork.h || sed -i 's|{"com.docker.network.container_iface_prefix", "circus"}};|{"com.docker.network.container_iface_prefix", "circus"},\n                                  {"com.docker.network.bridge.gateway_mode_ipv4", "nat-unprotected"}};|' include/CircusNetwork.h
grep -q '"com.docker.network.bridge.gateway_mode_ipv4", "nat-unprotected"' include/CircusNetwork.h
