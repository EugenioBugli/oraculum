#!/bin/bash
# Run oraculum in Docker with X11 forwarding

# Build the image
echo "Building Docker image..."
docker build -t oraculum:dev .

# Run with X11 forwarding
echo "Starting container with X11 forwarding..."
docker run -it --rm \
    --net=host \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /home/xps/.Xauthority:/root/.Xauthority \
    -e DISPLAY=$DISPLAY \
    -e QT_X11_GL_THREAD_SAFE=1 \
    oraculum:dev

echo "Container exited."
