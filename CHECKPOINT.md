# CHECKPOINT.md

> Last updated: 2026-04-10
> Branch: `fix/drag-freeze`
> Commit: b04a8ea (Add threaded animation to fix drag freeze)

## Original Task

User's oraculum froze the entire GNOME desktop when dragging the window. Requested: 
1. Way to run it in a Docker container with graphical interface for safe testing
2. Find and fix the memory leak causing the freeze

## Execution History

| Step | Action | Outcome |
|------|--------|---------|
| 1 | Analyzed code for memory leaks | Found FuncAnimation caching, thread cleanup issues |
| 2 | Diagnosed actual root cause | Not a memory leak — **main thread blocking during drag** |
| 3 | Created `viewer_fixed.py` | Better cleanup with atexit, but still blocking animation |
| 4 | Created `viewer_threaded.py` | **Real fix**: animation on background thread + non-blocking draw |
| 5 | Created Docker setup | Dockerfile + docker-run.sh for X11 forwarding |
| 6 | Switched `run_oraculum.py` default | Now imports viewer_threaded instead of viewer |
| 7 | Branch created & committed | `fix/drag-freeze` with 16 files, 1798 insertions |
| 8 | First retest | Process exits cleanly, threads shutdown properly |
| 9 | Second retest (quick) | User reported "just a horizontal line" field |

### Key Decisions

- **Background thread for animation**: Moved animation updates off main thread to free GTK event loop during drag
- **Non-blocking draw**: `fig.canvas.draw_idle()` instead of `fig.canvas.draw()` — lets GTK decide when to redraw
- **Aggressive documentation**: Wrote 5 comprehensive docs explaining the issue, root cause, and solution
- **Preserve original viewer.py**: Created new viewer_threaded.py; original untouched for comparison
- **Docker first**: Set up containerization so test hangs don't freeze the user's system

### Errors & Fixes

**Issue 1**: Initial analysis incorrectly focused on memory leaks  
**Fix**: Traced to actual GTK/X11 event loop starvation during window drag

**Issue 2**: FuncAnimation runs on main thread, blocks during drag  
**Fix**: Moved to background thread with `threading.Thread`

**Issue 3**: `fig.canvas.draw()` blocks, causing main thread freeze  
**Fix**: Switched to `fig.canvas.draw_idle()` (non-blocking mark-for-redraw)

**Issue 4**: Field rendering shows as "just a horizontal line"  
**Status**: Unclear if this is new issue or rendering glitch from threading. **Needs retest with visual inspection.**

## Lessons Learned

- ✓ GTK/X11 drag operations require the main thread to be free (blocking calls = freeze)
- ✓ `draw_idle()` is the right tool for background-threaded animations
- ✓ Docker provides excellent isolation for testing GUI apps that might freeze the desktop
- ✓ Daemon threads need explicit cleanup handlers (`atexit`) for graceful shutdown
- ? Tk backend + threading animation might have rendering quirks (field line issue)

## User Constraints

- **Git**: Use SSH URLs, never HTTPS
- **Commits**: No "Co-Authored-By: Claude" footer (user stated explicitly in CLAUDE.md)

## Current State

### What Is Working

- ✅ **Threaded animation runs without blocking main thread**
- ✅ **Process exits cleanly** (threads stop, sockets close, no zombies)
- ✅ **Docker builds successfully** with all dependencies
- ✅ **Receivers (UDP/GC) initialize and listen properly**
- ✅ **Configuration loads correctly** (field dimensions, display settings all present)

### What Is Broken / Incomplete

- ❌ **Field rendering issue**: User sees "just a horizontal line" instead of complete field with lines/markings
  - Unclear if this is:
    - A new threading issue with Tk backend
    - A display glitch from `draw_idle()` not being called enough
    - An axis limit/scaling problem
  - **Action needed**: Visual inspection + test_render.py output
  
- ❓ **Drag responsiveness not yet tested**: 
  - Process can start and exit cleanly, but key test (actually dragging window) not yet confirmed
  - This was the original freeze symptom

### File Map

```
fix/drag-freeze branch:
├── src/viewer_threaded.py          [NEW] Main fixed implementation
├── src/viewer_fixed.py             [NEW] Alternative conservative fix
├── run_oraculum.py                 [MODIFIED] Now imports viewer_threaded
├── run_oraculum_threaded.py        [NEW] Direct entry point
├── run_oraculum_debug.py           [NEW] Tracemalloc profiler
├── run_oraculum_profile.py         [NEW] Detailed memory tracker
├── test_render.py                  [NEW] Field rendering diagnostic
├── Dockerfile                       [NEW] Container for X11 testing
├── docker-run.sh                   [NEW] X11 forwarding helper
├── test_memory.sh                  [NEW] 30-second memory monitor
├── 
├── FIX_DRAG_FREEZE.md              [NEW] Solution explanation
├── DRAG_FREEZE_ROOT_CAUSE.md       [NEW] Root cause analysis with diagrams
├── DEBUG_INSTRUCTIONS.md           [NEW] Step-by-step debugging guide
├── MEMORY_LEAK_ANALYSIS.md         [NEW] Memory investigation (ultimately false alarm)
├── GRAPHICAL_DEBUGGING.md          [NEW] GUI testing reference
├── TESTING_SUMMARY.md              [NEW] Test results and what to verify
```

## Current Task (if ongoing)

**Status**: Blocked on field rendering verification

**What's happening**: 
- User reported field displays as "just a horizontal line" on second retest
- Need to determine if this is:
  - Threading/Tk backend issue
  - `draw_idle()` not being called frequently enough
  - Axis/scale problem
  
**What to check**:
```bash
# Test field rendering in isolation
python test_render.py
# (Should show complete field rectangle, not just a line)

# Retest main app with window open to visually inspect
python run_oraculum.py
# Open window, check field display, try dragging
```

## Next Steps

### Priority Order

1. **[CRITICAL] Verify field rendering**
   ```bash
   python test_render.py
   # Check: Does field render as complete rectangle or just horizontal line?
   # If line only: investigate Tk backend + threading interaction
   ```

2. **[CRITICAL] Test drag operation**
   - Run `python run_oraculum.py`
   - Try dragging the window multiple times
   - Verify: smooth/responsive (not frozen)
   - Close and verify clean exit

3. **[IF FIELD BROKEN] Debug rendering**
   - Check if `draw_idle()` is sufficient or needs `canvas.flush_figures()`
   - Inspect Tk event loop integration
   - May need to call `canvas.draw()` more frequently or add explicit updates

4. **[IF ALL GOOD] Prepare PR**
   - Merge to master with descriptive PR message
   - Run full test suite if one exists
   - Verify no other regressions

### Open Questions / Decisions Needed

1. **Is the field rendering issue real or a visual glitch?**
   - Run test_render.py and report what you see
   
2. **Is `draw_idle()` sufficient or do we need periodic `draw()` calls?**
   - May need to add a timer that calls `fig.canvas.draw()` every N seconds
   - Or check if `draw_idle()` needs to be called more frequently

3. **Should viewer_threaded.py be default long-term?**
   - Current: yes, it's the fix for the freeze
   - Alternative: keep original viewer.py as default, require opt-in to threaded
   - Recommendation: keep threaded as default (solves the original problem)

4. **What about viewer_fixed.py?**
   - Currently just an alternative with atexit cleanup
   - Should it be removed or kept as reference?
   - Recommendation: remove after threaded version is confirmed working
