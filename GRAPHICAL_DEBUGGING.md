# Running Oraculum with Graphical Debugging

## Quick Start (Safest Method)

```bash
cd /DATA/RoboCup/oraculum
./docker-run.sh
```

This builds and runs oraculum in a Docker container with X11 forwarding to your display. Any memory issues or hangs won't affect your system.

---

## What's Provided

### Docker Setup
- **`Dockerfile`** — Minimal Python image with matplotlib + TkAgg backend
- **`docker-run.sh`** — Helper script for X11 forwarding

### Memory Analysis Tools
- **`run_oraculum_debug.py`** — Simple tracemalloc snapshot
- **`run_oraculum_profile.py`** — Detailed allocation tracking with object counts
- **`test_memory.sh`** — Monitor memory over 30 seconds
- **`MEMORY_LEAK_ANALYSIS.md`** — Technical breakdown of suspected leaks

### Fixed Version
- **`src/viewer_fixed.py`** — Improved thread cleanup using `atexit` handler

---

## Methods to Run

### 1️⃣ Container (Recommended for Safety)

```bash
./docker-run.sh
```

| Pros | Cons |
|------|------|
| ✓ Can't freeze desktop | Needs Docker/Podman |
| ✓ Easy to kill | Slightly slower startup |
| ✓ Memory limits possible | |

### 2️⃣ Fixed Version (In-Place)

```bash
python -c "from src.viewer_fixed import main; main()"
```

| Pros | Cons |
|------|------|
| ✓ No Docker needed | ✗ Could still freeze |
| ✓ Same speed as original | ✗ Kills entire process on hang |

### 3️⃣ With Memory Profiling

```bash
# Real-time allocation tracking
python run_oraculum_profile.py

# OR with memory_profiler
pip install memory_profiler
python -m memory_profiler run_oraculum.py
```

### 4️⃣ Safe 30-Second Test

```bash
./test_memory.sh
```

Runs for 30 seconds, monitoring memory. Safe way to see if memory grows.

### 5️⃣ With Timeout

```bash
timeout 60s python run_oraculum.py
```

Auto-closes after 60 seconds. Good for automated testing.

---

## Finding the Memory Leak

### Step 1: Confirm with Container
```bash
./docker-run.sh
# Watch task manager / top in another terminal
# Close the window after 30 seconds
# Does memory keep growing? Does it hang?
```

### Step 2: Profile with Tracemalloc
```bash
python run_oraculum_profile.py
# Keep it open for ~30 seconds
# Press Ctrl+C
# Look for:
#   - Growing allocation sizes
#   - Unreachable objects (gc.garbage)
#   - Thread references that shouldn't be there
```

### Step 3: Memory Snapshot
```bash
python run_oraculum_debug.py
# Close window immediately
# Check the final memory report
```

---

## Key Findings (From Code Analysis)

### Probable Culprit: Thread Cleanup

**File:** `src/socket_client.py:116-145` and `src/gc_client.py:302-329`

```python
def _run(self) -> None:
    sock.settimeout(1.0)  # ← Problem: blocking for up to 1 sec
    while not self._stop_event.is_set():
        try:
            data, addr = sock.recvfrom(65535)  # ← Can block here
            # ... process ...
```

When you close the window:
1. `plt.show()` returns
2. `finally` block calls `receiver.stop()`
3. Thread is blocked in `recvfrom()` — still waiting for socket data
4. Takes up to 1 second to notice stop event
5. **If system is slow, GNOME might freeze during that second**

### Fix (Not Applied — You Decide)

Use non-blocking sockets with `select()`:

```python
sock.setblocking(False)
import select
ready = select.select([sock], [], [], 0.1)  # Check every 100ms
if ready[0]:
    data, addr = sock.recvfrom(65535)
```

This lets threads exit in <100ms instead of <1s.

---

## Understanding the Freeze

Gnome froze because:

1. **Matplotlib animation loop** (25 fps) keeps allocating memory
2. **UDP/GC threads** not stopping cleanly
3. **System memory fills up** → swap thrashing
4. **GNOME becomes unresponsive** due to I/O wait

The Docker container isolates this — if it hangs, only the container hangs, not GNOME.

---

## Recommendations

### For Testing Now
1. Use **Docker** (`./docker-run.sh`) — safest
2. If you want native speed, use **fixed viewer** — better cleanup
3. Run **memory profiling** to see where growth happens

### For Production Fix
1. **Option A:** Use `viewer_fixed.py` (zero code changes needed, just swap import)
2. **Option B:** Apply the select() fix to socket_client.py and gc_client.py
3. **Option C:** Both — the fixed viewer is lighter weight anyway

---

## Files Created

```
Dockerfile              # Docker image definition
docker-run.sh           # X11-forwarding helper script
run_oraculum_debug.py   # Simple memory tracer
run_oraculum_profile.py # Detailed profiler with object tracking
test_memory.sh          # 30-second safe test
src/viewer_fixed.py     # Improved version with cleanup
MEMORY_LEAK_ANALYSIS.md # Technical details
DEBUG_INSTRUCTIONS.md   # Step-by-step guide
GRAPHICAL_DEBUGGING.md  # This file
```

---

## Questions?

- **"Is Docker available?"** Check: `docker --version`
- **"How do I know if it works?"** Window should open, close cleanly, no freeze
- **"What if memory still grows?"** Check memory profile output (`run_oraculum_profile.py`)
- **"Can I use the fixed version?"** Yes! It's a drop-in replacement with better cleanup
