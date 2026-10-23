#!/bin/bash
# Jetson copy of /workspace/scripts/docker_entrypoint.sh: use the Orin GPU for ONNX Runtime when the GPU libraries are
# mounted at /opt/gpulibs (docker_config.gpu.yaml); else keep SPQR_NN_CPU=1 as on x86. Run in the workspace. Idempotent.
set -euo pipefail
f=scripts/docker_entrypoint.sh
[ -f $f.x86 ] || cp $f $f.x86
grep -q '/opt/gpulibs' $f || sed -i 's|^export SPQR_NN_CPU=1 .*|if [ -d /opt/gpulibs ]; then  # Jetson: CUDA/cuDNN/TensorRT mounted by docker_config.gpu.yaml\n    export LD_LIBRARY_PATH=/opt/gpulibs:/usr/local/cuda-12.6/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\nelse\n    export SPQR_NN_CPU=1  # simulation containers: no GPU, keep ONNX Runtime on the CPU (NeuralNetwork.cpp)\nfi|' $f
grep -q '/opt/gpulibs' $f
