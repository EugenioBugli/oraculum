#!/bin/bash
# Measurement only (Jetson copy of the robot code): log the YOLO inference time every 100 frames, so the GPU and CPU
# runs can be compared. Timer units are ms (Clock.h). Run in the workspace. Idempotent.
set -euo pipefail
f=src/app/nodes/vision/ObjectDetector.cpp
grep -q 'inference ms over' $f || sed -i 's|^    inferenceTimer_.end();|    inferenceTimer_.end();\n    if (inferenceTimer_.count() % 100 == 0)  // jetson measurement\n        LOG_INFO("ObjectDetector", "inference ms over " << inferenceTimer_.count() << " frames: mean " << inferenceTimer_.mean() << " min " << inferenceTimer_.min() << " max " << inferenceTimer_.max());|' $f
grep -q 'inference ms over' $f
