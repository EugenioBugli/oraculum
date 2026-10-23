#!/bin/bash
# After a fresh copy of a robot framework tree into ~/oraculum-sim-arm/workspace: the Jetson's build and simulation
# edits, without the measurement-only patches. Run in the workspace. Idempotent.
#  - pixi compilers for native aarch64 (patch_maximus.sh), optional GPU in the entrypoint (patch_entrypoint.sh),
#    supervisord for arm64 (supervisord.arm.conf);
#  - robot config for hosted simulation, as hosted/vm/provision.sh does on x86: scenario sim_fast, oraculum link on
#    (useRerun), Rerun output to /dev/null, no RGB logging.
set -euo pipefail
W=$HOME/oraculum-sim-arm
bash "$W/patch_maximus.sh"
bash "$W/patch_entrypoint.sh"
[ -f scripts/supervisord.conf.x86 ] || cp scripts/supervisord.conf scripts/supervisord.conf.x86
cp "$W/supervisord.arm.conf" scripts/supervisord.conf
cd src/app/config
sed -i -E "s/^scenario: \"[a-z_]+\"/scenario: \"${SCENARIO:-sim_fast}\"/" settings.yaml
sed -i 's/^useRerun: false/useRerun: true /' deploy.yaml
sed -i 's|^  mode: "connect"|  mode: "save"|; s|^  savePath: .*|  savePath: "/dev/null"|; s|^    rgb: true|    rgb: false|' settings.yaml
grep -q "^scenario: \"${SCENARIO:-sim_fast}\"" settings.yaml && grep -q '^useRerun: true' deploy.yaml && grep -q '^  mode: "save"' settings.yaml
echo "sim config ok"
