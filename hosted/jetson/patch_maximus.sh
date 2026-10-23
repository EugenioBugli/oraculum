#!/bin/bash
# Make the robot framework (/workspace tree) build natively on aarch64. Run in the workspace root. Idempotent.
# pixi.toml has compilers only for linux-64 (it cross-compiles for the robot): add the native aarch64 ones.
set -euo pipefail
grep -q '^gcc_linux-aarch64 = ">=14.3.0,<15"  # jetson-native' pixi.toml || sed -i '/^\[target.linux-aarch64.dependencies\]/a gcc_linux-aarch64 = ">=14.3.0,<15"  # jetson-native\ngxx_linux-aarch64 = ">=14.3.0,<15"  # jetson-native\nsysroot_linux-aarch64 = "==2.34"  # jetson-native' pixi.toml
grep -c 'jetson-native' pixi.toml | grep -qx 3
