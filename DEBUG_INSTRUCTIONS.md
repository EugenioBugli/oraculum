# Debugging Memory Leaks in Oraculum

## TL;DR — Safest Method

Run in a container to isolate any memory issues from your system:

```bash
cd /DATA/RoboCup/oraculum
chmod +x docker-run.sh
./docker-run.sh
```

This starts oraculum in an isolated Docker container with X11 forwarding. Any memory leaks won't freeze your system.

---

## The Freezing Problem

When you ran oraculum the first time, it froze GNOME. This is likely due to:

1. **Thread cleanup failure** — UDP receiver threads don't exit properly when window closes
2. **Memory growth** — matplotlib animation keeps references, growing ~1MB/frame at 25fps
3. **Direct GNOME integration** — matplotlib's GTK backend might deadlock with GNOME

---

## Solution Options

### Option 1: Docker Container (Recommended ✓)

Isolates the process completely. Safe for debugging.

```bash
cd /DATA/RoboCup/oraculum

# Build once
docker build -t oraculum:dev .

# Run (safe to kill if it hangs)
docker run -it --rm \
    --net=host \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $HOME/.Xauthority:/root/.Xauthority \
    -e DISPLAY=$DISPLAY \
    oraculum:dev python run_oraculum.py
```

Or use the helper script:
```bash
./docker-run.sh
```

**Advantages:**
- Hangs won't freeze your desktop
- Easy to kill with `Ctrl+C`
- Memory limits can be enforced
- Reproducible environment

---

### Option 2: Use Fixed Viewer (In-Place)

A patched version with better thread cleanup:

```bash
cd /DATA/RoboCup/oraculum

# Create a wrapper entry point
cat > run_oraculum_fixed.py << 'EOF'
from src.viewer_fixed import main

if __name__ == "__main__":
    main()
EOF

# Run it
python run_oraculum_fixed.py
```

**Advantages:**
- No Docker needed
- Same as original, but with cleanup fixes
- Good first test

---

### Option 3: Memory Profiling (Diagnose)

Find exactly where memory grows:

```bash
# Install if needed
pip install memory_profiler

# Profile line-by-line
python -m memory_profiler run_oraculum.py

# Or use tracemalloc
python run_oraculum_profile.py
```

Watch the output for growing memory allocations.

---

### Option 4: Debug with Timeout

Run with a timeout to auto-close after N seconds (safe test):

```bash
timeout 30s python run_oraculum.py
```

This runs for 30 seconds then auto-closes. Watch system memory with `top` or `gnome-system-monitor` in another terminal.

---

## What Was Fixed

### `src/viewer_fixed.py` Changes:

1. **Global cleanup handler** using `atexit.register()`
   - Ensures threads stop even if exception occurs
   - Properly closes sockets before threads exit

2. **Better thread state tracking**
   - Stores receiver references in `_cleanup_state` dict
   - Cleanup handler can forcefully stop threads

3. **Exception safety**
   - Each cleanup operation wrapped in try/except
   - Won't crash if partial initialization failed

### Socket Issues (Still Present):

The underlying socket threads in `socket_client.py` and `gc_client.py` still have:
- `sock.recvfrom()` blocking for 1 second timeout
- Daemon threads that might not notice stop event immediately

To fully fix, would need to:
```python
# In socket_client.py _run():
sock.setblocking(False)  # Non-blocking mode
# Then use select() or poll()
```

---

## Testing Plan

1. **First test** (safest):
   ```bash
   ./docker-run.sh
   # Close window immediately
   # Check: no GNOME freeze, container exits cleanly
   ```

2. **Memory test** (30 seconds):
   ```bash
   timeout 30s python run_oraculum.py &
   # In another terminal:
   watch -n 1 'ps aux | grep oraculum'
   # Watch for memory growing in RSS column
   ```

3. **Thread test** (with fixed version):
   ```bash
   python run_oraculum_fixed.py
   # Close window
   # Check console: should say "[Cleanup] Done." and exit within 3 seconds
   ```

---

## Likely Root Cause

In `src/socket_client.py:116-145` and `src/gc_client.py:302-329`:

The socket receive loop uses a 1-second timeout. When `plt.show()` returns (window closed), the `finally` block calls `receiver.stop()`, which sets a stop event. But:

- The thread might be blocking in `sock.recvfrom()` (line 126)
- Has up to 1 second left on timeout before checking stop event
- If window closes during that second, cleanup hangs

**Fix** (not applied, you might want to):
```python
def _run(self) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)  # Non-blocking!
    sock.bind(self._addr)
    
    import select
    while not self._stop_event.is_set():
        try:
            # select() respects timeout properly
            ready = select.select([sock], [], [], 0.1)
            if ready[0]:
                data, addr = sock.recvfrom(65535)
                # ... process ...
        except:
            pass
```

---

## Next Steps

1. Try **Option 1 (Docker)** first — safest
2. Then try **Option 2 (fixed viewer)** — if you want to avoid Docker
3. If still having issues, run **Option 3 (profiling)** and share output
