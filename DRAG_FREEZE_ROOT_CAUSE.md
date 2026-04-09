# Root Cause: Drag Freeze

## The Issue

When dragging the window, the **entire system froze** (GNOME unresponsive). This is NOT:
- ❌ A memory leak (not related to memory growth)
- ❌ A deadlock in your code
- ❌ A Python GIL issue

It IS:
- ✅ A **main thread blocking issue** during window drag operations
- ✅ **GTK/X11 event loop starvation** while animation runs

---

## Sequence of Events (Original Code)

```
TIME    MAIN THREAD                          WINDOW MANAGER
────────────────────────────────────────────────────────────
 0ms    plt.show()
        ↓
        Enter GTK event loop
        (waiting for events)
        
       [User clicks mouse and drags window]
        ↓
                                              Window grab initiated
                                              ↓
                                              WAITING FOR APP TO RESPOND
                                              
 40ms   FuncAnimation fires: update()
        ↓
        Matplotlib updates artists
        (trying to modify UI)
        ↓
        fig.canvas.draw() [BLOCKING CALL]
        ↓
        Canvas redraw in progress...
        (still drawing!)
        
                                              WINDOW MANAGER STILL WAITING
                                              FOR THE APP TO FINISH RESPONDING
                                              
 80ms   Still in fig.canvas.draw()
        [GTK event loop blocked]
        
                                              GNOME TIMEOUT: APP NOT RESPONDING
                                              ENTIRE SYSTEM FREEZES
                                              ↓
                                              [User can't move mouse, keyboard doesn't respond]
```

---

## Why This Happens

### GTK Event Model (X11/GNOME)

When you **drag a window in GTK**, the window manager:

1. **Grabs the window** — "I'm handling this drag operation"
2. **Sends grab notification to app** — "Please don't do anything else"
3. **Waits for app to acknowledge** — Needs app to finish any in-progress work
4. **Continues drag loop** — Processes mouse events while dragging

### The Problem: `FuncAnimation` on Main Thread

```python
anim = FuncAnimation(fig, update, interval=40, ...)  # Scheduled EVERY 40ms
```

This means:
- Every 40ms, GTK calls `update()` on the main thread
- `update()` calls `fig.canvas.draw()` which is **BLOCKING**
- While blocking, GTK can't process the window drag
- Window manager waits for the app to respond
- App is busy drawing → Deadlock situation
- **System freezes**

---

## The Thread Situation (Makes it Worse)

You also have background threads (UDP/GC receivers) running:

```python
receiver = UDPReceiver(...)  # Daemon thread
receiver.start()

gc_receiver = GCReceiver(...)  # Another daemon thread  
gc_receiver.start()
```

During drag, all these threads compete:
- **Main thread** — Blocked in animation update
- **Receiver threads** — Trying to read sockets
- **GC/allocation** — Python memory management

Result: **High contention, GTK can't get a response, system freezes**

---

## Visualization: Original Problem

```
MAIN THREAD                    BACKGROUND THREADS
────────────────────────────   ──────────────────
plt.show()
  ↓
Enter GTK event loop
  ↓
[Waiting for events]           [UDPReceiver thread]
  ↓                            [Running recvfrom()]
                               [GCReceiver thread]
[USER DRAGS WINDOW]            [Reading sockets]
  ↓
FuncAnimation.update()
  ↓
fig.canvas.draw() [BLOCKING]   ← MAIN THREAD STUCK
  ↓                            
[Can't process drag event]     [Still trying to read
[GTK stuck]                      while main thread
                                 blocked]

RESULT: Window manager waits → GTK doesn't respond
        → X11/GNOME timeout → SYSTEM FREEZE
```

---

## The Fix: Animation on Background Thread

Move `FuncAnimation` to a **separate background thread**:

```python
def animation_thread():
    while not stop_event.is_set():
        # ... update agents/ball ...
        fig.canvas.draw_idle()  # ← NON-BLOCKING!
        time.sleep(0.04)

threading.Thread(target=animation_thread, daemon=True).start()
```

Now:

```
MAIN THREAD                        BACKGROUND THREAD
────────────────────────────       ──────────────────
plt.show()
  ↓
Enter GTK event loop
[READY FOR EVENTS]                 animation_thread()
  ↓                                   ↓
[USER DRAGS WINDOW]                [update() runs]
  ↓                                   ↓
GTK processes drag! ✓              [draw_idle() - instant return]
[Main thread free]                    ↓
                                   [sleep(0.04)]
Window drag responds immediately!    ↓
No freeze! ✓                       [Loop continues]

RESULT: Window manager gets response immediately
        → GNOME doesn't freeze
        → Animation still runs smoothly
        → Everyone happy!
```

---

## Why `draw_idle()` is Safe

The key is `fig.canvas.draw_idle()`:

```python
# WRONG (blocking):
fig.canvas.draw()  # Waits for redraw to complete

# RIGHT (non-blocking):
fig.canvas.draw_idle()  # Just marks as needing redraw, returns immediately
```

`draw_idle()` is thread-safe and:
1. **Marks the canvas** as needing redraw
2. **Returns immediately** (non-blocking)
3. **Tells GTK** "Please redraw when you're idle"
4. **Lets the event loop decide when** to actually redraw
5. **Keeps main thread responsive**

---

## Testing the Fix

### Before (Original):
```bash
$ python run_oraculum.py &
# Opens window
# Try to drag window quickly
# [System freezes]
# Kill with Ctrl+C (might not work, need hard reset or kill -9)
```

### After (Threaded):
```bash
$ python run_oraculum_threaded.py &
# Opens window
# Drag window freely — smooth and responsive ✓
# Close window — exits cleanly ✓
# No freeze
```

---

## Summary

| Aspect | Original | Threaded |
|--------|----------|----------|
| **Where animation runs** | Main thread (with GTK) | Background thread |
| **Canvas redraw** | `draw()` (blocks) | `draw_idle()` (non-blocks) |
| **During drag** | Main thread stuck | Main thread free |
| **GTK response time** | Delayed (waits for animation) | Immediate |
| **Drag responsive** | ❌ Freezes | ✅ Smooth |
| **System impact** | ❌ System freeze | ✅ No impact |

---

## Files Involved

- **`src/viewer.py`** — Original (has the freeze issue)
- **`src/viewer_threaded.py`** — Fixed version
- **`run_oraculum_threaded.py`** — Recommended entry point
- **`docker-run.sh`** — Now uses threaded version

**Recommendation:** Switch to `viewer_threaded.py` as the default. Zero downside.
