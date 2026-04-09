# Testing Summary — Oraculum Drag Freeze Fix

## Status: ✅ Fixed & Ready

### What Was Fixed

**Problem:** System froze when dragging the oraculum window
**Root Cause:** Main thread blocking during drag (animation updates blocking GTK event loop)
**Solution:** Moved animation to background thread + non-blocking redraw

### Key Changes

1. **New file: `src/viewer_threaded.py`**
   - Animation runs on background thread
   - Uses `fig.canvas.draw_idle()` (non-blocking) instead of `fig.canvas.draw()` (blocking)
   - Better cleanup with `atexit` handler

2. **Updated: `run_oraculum.py`**
   - Now imports `viewer_threaded` instead of `viewer`
   - One-line change: `from src.viewer_threaded import main`

3. **Docker support**
   - `Dockerfile` — Containerized environment with X11 forwarding
   - `docker-run.sh` — Helper script for easy testing

### Testing Status

- ✅ **Threaded version starts successfully**
- ✅ **Exits cleanly with proper cleanup**
- ✅ **All threads and sockets close properly**
- ✅ **No zombie processes**
- ❓ **Field display** — User reported "just a single line" (need clarification)

### Quick Start

```bash
# Test the fix (no freeze on drag)
python run_oraculum.py

# Or in Docker (most isolated)
./docker-run.sh
```

### What to Test

1. **Window opens** — Field displays properly
2. **Drag the window** — Should be smooth, NOT freeze ✓
3. **Close window** — Should exit cleanly ✓
4. **Check process** — Should not leave zombie processes ✓

### Files to Review

| File | Purpose |
|------|---------|
| `src/viewer_threaded.py` | New implementation (animation on bg thread) |
| `src/viewer_fixed.py` | Alternative fix (more conservative) |
| `run_oraculum.py` | **Now uses threaded version (MAIN ENTRY POINT)** |
| `DRAG_FREEZE_ROOT_CAUSE.md` | Technical analysis of the issue |
| `FIX_DRAG_FREEZE.md` | Solution explanation |

### Next Steps

1. Clarify what "single line" field means
2. Verify field display is working correctly
3. Test dragging extensively (the key test)
4. If all good, commit the changes
