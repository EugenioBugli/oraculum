# Memory Leak Analysis - Oraculum

## Identified Issues

### 1. **FuncAnimation Caching** (viewer.py:245)
```python
anim = FuncAnimation(fig, update, interval=int(dt * 1000), blit=False, cache_frame_data=False)
```
- **Problem**: Even with `cache_frame_data=False`, matplotlib 3.8+ may keep frame references
- **Impact**: ~25 frames/sec × ~1MB per frame = growth over time

### 2. **Thread Cleanup on Exit** (viewer.py:254-257)
```python
finally:
    if receiver is not None:
        receiver.stop()
    if gc_receiver is not None:
        gc_receiver.stop()
```
- **Problem**: 2-second timeout (`_thread.join(timeout=2.0)`) may not be enough
- **Problem**: Threads might not exit if stuck in `sock.recvfrom()` → stuck in select()
- **Impact**: Orphaned daemon threads holding memory/sockets

### 3. **Matplotlib Reference Cycles**
- **Problem**: Text artists (state_t, half_t, etc.) and figure patches create reference cycles
- **Impact**: GC struggles to collect, especially if exception occurs during animation

## Quick Debugging Steps

### Option 1: Run with Memory Profiler
```bash
# Install memory_profiler
pip install memory_profiler

# Profile the main function
python -m memory_profiler run_oraculum.py
```

### Option 2: Run in Container (Safest)
```bash
chmod +x docker-run.sh
./docker-run.sh
```
The container isolates memory leaks so they won't freeze your system.

### Option 3: Run with Profiling Script
```bash
# Detailed allocation tracking
python run_oraculum_profile.py

# Just tracemalloc snapshots
python run_oraculum_debug.py
```

## Suspected Root Cause
Most likely: **Thread socket handler not releasing resources properly** in `socket_client.py:_run()` or `gc_client.py:_run()` when the window closes.

When you close the matplotlib window:
1. `plt.show()` exits
2. `finally` block calls `receiver.stop()`
3. Thread's `_stop_event.set()` is called
4. But if the thread is blocked in `sock.recvfrom()`, it may take 1+ second to notice
5. If matplotlib window close is fast, threads might not cleanup properly → memory held

## Recommendations

1. **Use Container for Testing** — safest and most isolated
2. **Add Timeout Monitoring** — check if threads exit properly
3. **Consider Process-Level Isolation** — run in subprocess with memory limits
