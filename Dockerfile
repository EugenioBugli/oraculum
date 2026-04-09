# Use lightweight Python image with GUI support
FROM python:3.12-slim

# Install X11 and graphics dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libx11-6 \
    libxext6 \
    libsm6 \
    libxrender1 \
    tk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the project
COPY . .

# Install pixi environment dependencies from pyproject.toml or requirements
RUN pip install --no-cache-dir \
    matplotlib \
    pyyaml \
    numpy

# Set environment for X11 forwarding
ENV DISPLAY=:0
ENV QT_X11_GL_THREAD_SAFE=1
ENV MPLBACKEND=TkAgg

# Use threaded version by default (no freeze while dragging)
CMD ["python", "run_oraculum_threaded.py"]
